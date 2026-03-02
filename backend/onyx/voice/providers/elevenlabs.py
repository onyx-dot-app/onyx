import asyncio
import base64
import json
from collections.abc import AsyncIterator

import aiohttp

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
        self, _text: str, _voice: str | None = None, _speed: float = 1.0
    ) -> AsyncIterator[bytes]:
        raise NotImplementedError("ElevenLabs TTS not yet implemented")
        yield b""  # Required for async generator

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
