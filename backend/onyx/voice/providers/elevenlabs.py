import asyncio
import base64
import json
from collections.abc import AsyncIterator

import aiohttp

from onyx.voice.interface import StreamingSynthesizerProtocol
from onyx.voice.interface import StreamingTranscriberProtocol
from onyx.voice.interface import TranscriptResult
from onyx.voice.interface import VoiceProviderInterface

# Common ElevenLabs voices
ELEVENLABS_VOICES = [
    {"id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel"},
    {"id": "AZnzlk1XvdvUeBnXmlld", "name": "Domi"},
    {"id": "EXAVITQu4vr4xnSDxMaL", "name": "Bella"},
    {"id": "ErXwobaYiN019PkySvjV", "name": "Antoni"},
    {"id": "MF3mGyEYCl7XYWbV9V6O", "name": "Elli"},
    {"id": "TxGEqnHWrfWFTfGW9XjX", "name": "Josh"},
    {"id": "VR6AewLTigWG4xSOukaG", "name": "Arnold"},
    {"id": "pNInz6obpgDQGcFmaJgB", "name": "Adam"},
    {"id": "yoZ06aMxZJJ28mfd3POQ", "name": "Sam"},
]


class ElevenLabsStreamingTranscriber(StreamingTranscriberProtocol):
    """Streaming transcription session using ElevenLabs Scribe Realtime API."""

    def __init__(self, api_key: str, model: str = "scribe_v2"):
        # Import logger first
        from onyx.utils.logger import setup_logger

        self._logger = setup_logger()

        self._logger.info(
            f"ElevenLabsStreamingTranscriber: initializing with model {model}"
        )
        self.api_key = api_key
        self.model = model
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._session: aiohttp.ClientSession | None = None
        self._transcript_queue: asyncio.Queue[TranscriptResult | None] = asyncio.Queue()
        self._final_transcript = ""
        self._receive_task: asyncio.Task | None = None
        self._closed = False

    async def connect(self) -> None:
        """Establish WebSocket connection to ElevenLabs."""
        self._logger.info(
            "ElevenLabsStreamingTranscriber: connecting to ElevenLabs API"
        )
        self._session = aiohttp.ClientSession()
        url = (
            f"wss://api.elevenlabs.io/v1/speech-to-text/realtime?model_id={self.model}"
        )

        try:
            self._ws = await self._session.ws_connect(
                url,
                headers={"xi-api-key": self.api_key},
            )
            self._logger.info("ElevenLabsStreamingTranscriber: connected successfully")
        except Exception as e:
            self._logger.error(
                f"ElevenLabsStreamingTranscriber: failed to connect: {e}"
            )
            raise

        # Start receiving transcripts in background
        self._receive_task = asyncio.create_task(self._receive_loop())

    async def _receive_loop(self) -> None:
        """Background task to receive transcripts from WebSocket."""
        self._logger.info("ElevenLabsStreamingTranscriber: receive loop started")
        if not self._ws:
            self._logger.warning(
                "ElevenLabsStreamingTranscriber: no WebSocket connection"
            )
            return

        try:
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    msg_type = data.get("type", "unknown")
                    self._logger.debug(
                        f"ElevenLabsStreamingTranscriber: received message type: {msg_type}"
                    )

                    # Handle different message types from ElevenLabs
                    if msg_type == "transcript":
                        text = data.get("text", "")
                        if text:
                            self._logger.info(
                                f"ElevenLabsStreamingTranscriber: transcript: {text[:50]}..."
                            )
                            self._final_transcript = text
                            await self._transcript_queue.put(
                                TranscriptResult(text=text, is_vad_end=False)
                            )
                    elif msg_type == "final_transcript":
                        text = data.get("text", "")
                        if text:
                            self._logger.info(
                                f"ElevenLabsStreamingTranscriber: final transcript: {text[:50]}..."
                            )
                            self._final_transcript = text
                            # final_transcript indicates VAD end
                            await self._transcript_queue.put(
                                TranscriptResult(text=text, is_vad_end=True)
                            )
                    elif msg_type == "error":
                        error_msg = data.get("message", "Unknown error")
                        self._logger.error(
                            f"ElevenLabsStreamingTranscriber: error from API: {error_msg}"
                        )
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    self._logger.info(
                        "ElevenLabsStreamingTranscriber: WebSocket closed by server"
                    )
                    break
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    self._logger.error(
                        "ElevenLabsStreamingTranscriber: WebSocket error"
                    )
                    break
        except Exception as e:
            self._logger.error(
                f"ElevenLabsStreamingTranscriber: error in receive loop: {e}"
            )
        finally:
            self._logger.info("ElevenLabsStreamingTranscriber: receive loop ended")
            await self._transcript_queue.put(None)  # Signal end

    async def send_audio(self, chunk: bytes) -> None:
        """Send an audio chunk for transcription."""
        if self._ws and not self._closed:
            # ElevenLabs expects base64-encoded audio in a JSON message
            message = {
                "type": "input_audio_chunk",
                "audio": base64.b64encode(chunk).decode("utf-8"),
            }
            await self._ws.send_str(json.dumps(message))

    async def receive_transcript(self) -> TranscriptResult | None:
        """Receive next transcript. Returns None when done."""
        try:
            return await asyncio.wait_for(self._transcript_queue.get(), timeout=0.1)
        except asyncio.TimeoutError:
            return TranscriptResult(
                text="", is_vad_end=False
            )  # No transcript yet, but not done

    async def close(self) -> str:
        """Close the session and return final transcript."""
        self._closed = True
        if self._ws:
            # Signal end of audio
            await self._ws.send_str(json.dumps({"type": "flush"}))
            await self._ws.close()
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
        if self._session:
            await self._session.close()
        return self._final_transcript

    def reset_transcript(self) -> None:
        """Reset accumulated transcript. Call after auto-send to start fresh."""
        self._final_transcript = ""


class ElevenLabsStreamingSynthesizer(StreamingSynthesizerProtocol):
    """Real-time streaming TTS using ElevenLabs WebSocket API."""

    def __init__(
        self,
        api_key: str,
        voice_id: str,
        model_id: str = "eleven_multilingual_v2",
        output_format: str = "mp3_44100_64",
    ):
        from onyx.utils.logger import setup_logger

        self._logger = setup_logger()
        self.api_key = api_key
        self.voice_id = voice_id
        self.model_id = model_id
        self.output_format = output_format
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._session: aiohttp.ClientSession | None = None
        self._audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._receive_task: asyncio.Task | None = None
        self._closed = False

    async def connect(self) -> None:
        """Establish WebSocket connection to ElevenLabs TTS."""
        self._logger.info("ElevenLabsStreamingSynthesizer: connecting")
        self._session = aiohttp.ClientSession()

        # WebSocket URL for streaming input TTS with output format for streaming compatibility
        # Using mp3_44100_64 for good quality with smaller chunks for real-time playback
        url = (
            f"wss://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}/stream-input"
            f"?model_id={self.model_id}&output_format={self.output_format}"
        )

        self._ws = await self._session.ws_connect(
            url,
            headers={"xi-api-key": self.api_key},
        )

        # Send initial configuration with generation settings optimized for streaming
        await self._ws.send_str(
            json.dumps(
                {
                    "text": " ",  # Initial space to start the stream
                    "voice_settings": {
                        "stability": 0.5,
                        "similarity_boost": 0.75,
                    },
                    "generation_config": {
                        "chunk_length_schedule": [
                            120,
                            160,
                            250,
                            290,
                        ],  # Optimized chunk sizes for streaming
                    },
                    "xi_api_key": self.api_key,
                }
            )
        )

        # Start receiving audio in background
        self._receive_task = asyncio.create_task(self._receive_loop())
        self._logger.info("ElevenLabsStreamingSynthesizer: connected")

    async def _receive_loop(self) -> None:
        """Background task to receive audio chunks from WebSocket."""
        if not self._ws:
            return

        try:
            async for msg in self._ws:
                if self._closed:
                    break
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    if "audio" in data and data["audio"]:
                        # Audio is base64 encoded
                        audio_bytes = base64.b64decode(data["audio"])
                        await self._audio_queue.put(audio_bytes)
                elif msg.type == aiohttp.WSMsgType.BINARY:
                    await self._audio_queue.put(msg.data)
                elif msg.type in (
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.ERROR,
                ):
                    break
        except Exception as e:
            self._logger.error(f"ElevenLabsStreamingSynthesizer receive error: {e}")
        finally:
            await self._audio_queue.put(None)  # Signal end of stream

    async def send_text(self, text: str) -> None:
        """Send text to be synthesized."""
        if self._ws and not self._closed:
            await self._ws.send_str(
                json.dumps(
                    {
                        "text": text,
                        "try_trigger_generation": True,
                    }
                )
            )

    async def receive_audio(self) -> bytes | None:
        """Receive next audio chunk."""
        try:
            return await asyncio.wait_for(self._audio_queue.get(), timeout=0.1)
        except asyncio.TimeoutError:
            return b""  # No audio yet, but not done

    async def flush(self) -> None:
        """Signal end of text input to generate remaining audio."""
        if self._ws and not self._closed:
            await self._ws.send_str(json.dumps({"text": ""}))

    async def close(self) -> None:
        """Close the session."""
        self._closed = True
        if self._ws:
            await self._ws.close()
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
        if self._session:
            await self._session.close()


class ElevenLabsVoiceProvider(VoiceProviderInterface):
    """ElevenLabs voice provider."""

    def __init__(
        self,
        api_key: str | None,
        api_base: str | None = None,
        stt_model: str | None = None,
        tts_model: str | None = None,
        default_voice: str | None = None,
    ):
        self.api_key = api_key
        self.api_base = api_base or "https://api.elevenlabs.io"
        self.stt_model = stt_model or "scribe_v2"
        self.tts_model = tts_model or "eleven_multilingual_v2"
        self.default_voice = default_voice

    async def transcribe(self, _audio_data: bytes, _audio_format: str) -> str:
        raise NotImplementedError("ElevenLabs STT not yet implemented")

    async def synthesize_stream(
        self, text: str, voice: str | None = None, _speed: float = 1.0
    ) -> AsyncIterator[bytes]:
        """
        Convert text to audio using ElevenLabs TTS with streaming.

        Args:
            text: Text to convert to speech
            voice: Voice ID (defaults to provider's default voice or Rachel)
            speed: Playback speed multiplier (not directly supported, ignored)

        Yields:
            Audio data chunks (mp3 format)
        """
        if not self.api_key:
            raise ValueError("ElevenLabs API key required for TTS")

        voice_id = voice or self.default_voice or "21m00Tcm4TlvDq8ikWAM"  # Rachel

        url = f"{self.api_base}/v1/text-to-speech/{voice_id}/stream"

        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }

        payload = {
            "text": text,
            "model_id": self.tts_model,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
            },
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise RuntimeError(f"ElevenLabs TTS failed: {error_text}")

                # Use 8192 byte chunks for smoother streaming
                async for chunk in response.content.iter_chunked(8192):
                    if chunk:
                        yield chunk

    def get_available_voices(self) -> list[dict[str, str]]:
        """Return common ElevenLabs voices."""
        return ELEVENLABS_VOICES.copy()

    def get_available_stt_models(self) -> list[dict[str, str]]:
        return [
            {"id": "scribe_v2", "name": "Scribe v2 (Recommended)"},
            {"id": "scribe_v1", "name": "Scribe v1"},
        ]

    def get_available_tts_models(self) -> list[dict[str, str]]:
        return [
            {"id": "eleven_multilingual_v2", "name": "Multilingual v2"},
            {"id": "eleven_turbo_v2_5", "name": "Turbo v2.5"},
            {"id": "eleven_monolingual_v1", "name": "Monolingual v1"},
        ]

    def supports_streaming_stt(self) -> bool:
        """ElevenLabs supports streaming via Scribe Realtime API."""
        return True

    def supports_streaming_tts(self) -> bool:
        """ElevenLabs supports real-time streaming TTS via WebSocket."""
        return True

    async def create_streaming_transcriber(
        self, _audio_format: str = "webm"
    ) -> ElevenLabsStreamingTranscriber:
        """Create a streaming transcription session."""
        if not self.api_key:
            raise ValueError("API key required for streaming transcription")
        transcriber = ElevenLabsStreamingTranscriber(
            api_key=self.api_key,
            model=self.stt_model or "scribe_v2",
        )
        await transcriber.connect()
        return transcriber

    async def create_streaming_synthesizer(
        self, voice: str | None = None, _speed: float = 1.0
    ) -> ElevenLabsStreamingSynthesizer:
        """Create a streaming TTS session."""
        if not self.api_key:
            raise ValueError("API key required for streaming TTS")
        voice_id = voice or self.default_voice or "21m00Tcm4TlvDq8ikWAM"
        synthesizer = ElevenLabsStreamingSynthesizer(
            api_key=self.api_key,
            voice_id=voice_id,
            model_id=self.tts_model or "eleven_multilingual_v2",
            # Use mp3_44100_64 for streaming - good balance of quality and chunk size
            output_format="mp3_44100_64",
        )
        await synthesizer.connect()
        return synthesizer
