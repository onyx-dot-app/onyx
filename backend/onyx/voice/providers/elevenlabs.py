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

    def __init__(
        self,
        api_key: str,
        model: str = "scribe_v2_realtime",
        input_sample_rate: int = 24000,  # What frontend sends
        target_sample_rate: int = 16000,  # What ElevenLabs expects
        language_code: str = "en",
    ):
        # Import logger first
        from onyx.utils.logger import setup_logger

        self._logger = setup_logger()

        self._logger.info(
            f"ElevenLabsStreamingTranscriber: initializing with model {model}"
        )
        self.api_key = api_key
        self.model = model
        self.input_sample_rate = input_sample_rate
        self.target_sample_rate = target_sample_rate
        self.language_code = language_code
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

        # VAD is configured via query parameters
        # commit_strategy=vad enables automatic transcript commit on silence detection
        url = (
            f"wss://api.elevenlabs.io/v1/speech-to-text/realtime"
            f"?model_id={self.model}"
            f"&sample_rate={self.target_sample_rate}"
            f"&language_code={self.language_code}"
            f"&commit_strategy=vad"
            f"&vad_silence_threshold_secs=1.0"
            f"&vad_threshold=0.4"
            f"&min_speech_duration_ms=100"
            f"&min_silence_duration_ms=300"
        )
        self._logger.info(
            f"ElevenLabsStreamingTranscriber: connecting to {url} "
            f"(input={self.input_sample_rate}Hz, target={self.target_sample_rate}Hz)"
        )

        try:
            self._ws = await self._session.ws_connect(
                url,
                headers={"xi-api-key": self.api_key},
            )
            self._logger.info(
                f"ElevenLabsStreamingTranscriber: connected successfully, "
                f"ws.closed={self._ws.closed}, close_code={self._ws.close_code}"
            )
        except Exception as e:
            self._logger.error(
                f"ElevenLabsStreamingTranscriber: failed to connect: {e}"
            )
            if self._session:
                await self._session.close()
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
                self._logger.debug(
                    f"ElevenLabsStreamingTranscriber: raw message type: {msg.type}"
                )
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                    except json.JSONDecodeError:
                        self._logger.error(
                            f"ElevenLabsStreamingTranscriber: failed to parse JSON: {msg.data[:200]}"
                        )
                        continue

                    # ElevenLabs uses message_type field
                    msg_type = data.get("message_type", data.get("type", ""))  # type: ignore[possibly-undefined]
                    self._logger.info(
                        f"ElevenLabsStreamingTranscriber: received message_type: '{msg_type}', data keys: {list(data.keys())}"
                    )
                    # Check for error in various formats
                    if "error" in data or msg_type == "error":
                        error_msg = data.get("error", data.get("message", data))
                        self._logger.error(
                            f"ElevenLabsStreamingTranscriber: API error: {error_msg}"
                        )
                        continue

                    # Handle different message types from ElevenLabs Scribe API
                    if msg_type == "session_started":
                        # Session started successfully
                        self._logger.info(
                            f"ElevenLabsStreamingTranscriber: session started, "
                            f"id={data.get('session_id')}, config={data.get('config')}"
                        )
                    elif msg_type == "partial_transcript":
                        # Partial transcript (interim result)
                        text = data.get("text", "")
                        if text:
                            self._logger.info(
                                f"ElevenLabsStreamingTranscriber: partial_transcript: {text[:50]}..."
                            )
                            self._final_transcript = text
                            await self._transcript_queue.put(
                                TranscriptResult(text=text, is_vad_end=False)
                            )
                    elif msg_type == "committed_transcript":
                        # Final/committed transcript (VAD detected end of utterance)
                        text = data.get("text", "")
                        if text:
                            self._logger.info(
                                f"ElevenLabsStreamingTranscriber: committed_transcript: {text[:50]}..."
                            )
                            self._final_transcript = text
                            await self._transcript_queue.put(
                                TranscriptResult(text=text, is_vad_end=True)
                            )
                    elif msg_type == "utterance_end":
                        # VAD detected end of speech
                        text = data.get("text", "") or self._final_transcript
                        if text:
                            self._logger.info(
                                f"ElevenLabsStreamingTranscriber: utterance_end: {text[:50]}..."
                            )
                            self._final_transcript = text
                            await self._transcript_queue.put(
                                TranscriptResult(text=text, is_vad_end=True)
                            )
                    elif msg_type == "session_ended":
                        self._logger.info(
                            "ElevenLabsStreamingTranscriber: session ended"
                        )
                        break
                    else:
                        # Log unhandled message types with full data for debugging
                        self._logger.warning(
                            f"ElevenLabsStreamingTranscriber: unhandled message_type: {msg_type}, full data: {data}"
                        )
                elif msg.type == aiohttp.WSMsgType.BINARY:
                    self._logger.debug(
                        f"ElevenLabsStreamingTranscriber: received binary message: {len(msg.data)} bytes"
                    )
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    close_code = self._ws.close_code if self._ws else "N/A"
                    self._logger.info(
                        "ElevenLabsStreamingTranscriber: WebSocket closed by "
                        f"server, close_code={close_code}"
                    )
                    break
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    self._logger.error(
                        f"ElevenLabsStreamingTranscriber: WebSocket error: {self._ws.exception() if self._ws else 'N/A'}"
                    )
                    break
                elif msg.type == aiohttp.WSMsgType.CLOSE:
                    self._logger.info(
                        f"ElevenLabsStreamingTranscriber: WebSocket CLOSE frame received, data={msg.data}, extra={msg.extra}"
                    )
                    break
        except Exception as e:
            self._logger.error(
                f"ElevenLabsStreamingTranscriber: error in receive loop: {e}",
                exc_info=True,
            )
        finally:
            close_code = self._ws.close_code if self._ws else "N/A"
            self._logger.info(
                f"ElevenLabsStreamingTranscriber: receive loop ended, close_code={close_code}"
            )
            await self._transcript_queue.put(None)  # Signal end

    def _resample_pcm16(self, data: bytes) -> bytes:
        """Resample PCM16 audio from input_sample_rate to target_sample_rate."""
        import struct

        if self.input_sample_rate == self.target_sample_rate:
            return data

        # Parse int16 samples
        num_samples = len(data) // 2
        samples = list(struct.unpack(f"<{num_samples}h", data))

        # Calculate resampling ratio
        ratio = self.input_sample_rate / self.target_sample_rate
        new_length = int(num_samples / ratio)

        # Linear interpolation resampling
        resampled = []
        for i in range(new_length):
            src_idx = i * ratio
            idx_floor = int(src_idx)
            idx_ceil = min(idx_floor + 1, num_samples - 1)
            frac = src_idx - idx_floor
            sample = int(samples[idx_floor] * (1 - frac) + samples[idx_ceil] * frac)
            # Clamp to int16 range
            sample = max(-32768, min(32767, sample))
            resampled.append(sample)

        return struct.pack(f"<{len(resampled)}h", *resampled)

    async def send_audio(self, chunk: bytes) -> None:
        """Send an audio chunk for transcription."""
        if not self._ws:
            self._logger.warning("send_audio: no WebSocket connection")
            return
        if self._closed:
            self._logger.warning("send_audio: transcriber is closed")
            return
        if self._ws.closed:
            self._logger.warning(
                f"send_audio: WebSocket is closed, close_code={self._ws.close_code}"
            )
            return

        try:
            # Resample from input rate (24kHz) to target rate (16kHz)
            resampled = self._resample_pcm16(chunk)
            # ElevenLabs expects input_audio_chunk message format with audio_base_64
            audio_b64 = base64.b64encode(resampled).decode("utf-8")
            message = {
                "message_type": "input_audio_chunk",
                "audio_base_64": audio_b64,
                "sample_rate": self.target_sample_rate,
            }
            self._logger.info(
                f"send_audio: {len(chunk)} bytes -> {len(resampled)} bytes (resampled) -> {len(audio_b64)} chars base64"
            )
            await self._ws.send_str(json.dumps(message))
            self._logger.info("send_audio: message sent successfully")
        except Exception as e:
            self._logger.error(f"send_audio: failed to send: {e}", exc_info=True)

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
        self._logger.info("ElevenLabsStreamingTranscriber: closing session")
        self._closed = True
        if self._ws and not self._ws.closed:
            try:
                # Just close the WebSocket - ElevenLabs Scribe doesn't need a special end message
                self._logger.info(
                    "ElevenLabsStreamingTranscriber: closing WebSocket connection"
                )
                await self._ws.close()
            except Exception as e:
                self._logger.debug(f"Error closing WebSocket: {e}")
        if self._receive_task and not self._receive_task.done():
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
        if self._session and not self._session.closed:
            await self._session.close()
        return self._final_transcript

    def reset_transcript(self) -> None:
        """Reset accumulated transcript. Call after auto-send to start fresh."""
        self._final_transcript = ""


class ElevenLabsStreamingSynthesizer(StreamingSynthesizerProtocol):
    """Real-time streaming TTS using ElevenLabs WebSocket API.

    Uses ElevenLabs' stream-input WebSocket which processes text as one
    continuous stream and returns audio in order.
    """

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
        """Background task to receive audio chunks from WebSocket.

        Audio is returned in order as one continuous stream.
        """
        if not self._ws:
            return

        chunk_count = 0
        total_bytes = 0
        try:
            async for msg in self._ws:
                if self._closed:
                    self._logger.info(
                        "ElevenLabsStreamingSynthesizer: closed flag set, stopping "
                        "receive loop"
                    )
                    break
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    # Process audio if present
                    if "audio" in data and data["audio"]:
                        audio_bytes = base64.b64decode(data["audio"])
                        chunk_count += 1
                        total_bytes += len(audio_bytes)
                        await self._audio_queue.put(audio_bytes)

                    # Check isFinal separately - a message can have both audio AND isFinal
                    if "isFinal" in data:
                        self._logger.info(
                            f"ElevenLabsStreamingSynthesizer: received isFinal={data['isFinal']}, "
                            f"chunks so far: {chunk_count}, bytes: {total_bytes}"
                        )
                        if data.get("isFinal"):
                            self._logger.info(
                                "ElevenLabsStreamingSynthesizer: isFinal=true, signaling end of audio"
                            )
                            await self._audio_queue.put(None)

                    # Check for errors
                    if "error" in data or data.get("type") == "error":
                        self._logger.error(
                            f"ElevenLabsStreamingSynthesizer: received error: {data}"
                        )
                elif msg.type == aiohttp.WSMsgType.BINARY:
                    chunk_count += 1
                    total_bytes += len(msg.data)
                    await self._audio_queue.put(msg.data)
                elif msg.type in (
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.ERROR,
                ):
                    self._logger.info(
                        f"ElevenLabsStreamingSynthesizer: WebSocket closed/error, type={msg.type}"
                    )
                    break
        except Exception as e:
            self._logger.error(f"ElevenLabsStreamingSynthesizer receive error: {e}")
        finally:
            self._logger.info(
                f"ElevenLabsStreamingSynthesizer: receive loop ended, {chunk_count} chunks, {total_bytes} bytes"
            )
            await self._audio_queue.put(None)  # Signal end of stream

    async def send_text(self, text: str) -> None:
        """Send text to be synthesized.

        ElevenLabs processes text as a continuous stream and returns
        audio in order. We let ElevenLabs handle buffering via chunk_length_schedule
        and only force generation when flush() is called at the end.

        Args:
            text: Text to synthesize
        """
        if self._ws and not self._closed and text.strip():
            self._logger.info(
                f"ElevenLabsStreamingSynthesizer: sending text ({len(text)} chars): '{text}'"
            )
            # Let ElevenLabs buffer and auto-generate based on chunk_length_schedule
            # Don't trigger generation here - wait for flush() at the end
            await self._ws.send_str(
                json.dumps(
                    {
                        "text": text + " ",  # Space for natural speech flow
                    }
                )
            )
            self._logger.info("ElevenLabsStreamingSynthesizer: text sent successfully")
        else:
            self._logger.warning(
                f"ElevenLabsStreamingSynthesizer: skipping send_text - "
                f"ws={self._ws is not None}, closed={self._closed}, text='{text[:30] if text else ''}'"
            )

    async def receive_audio(self) -> bytes | None:
        """Receive next audio chunk."""
        try:
            return await asyncio.wait_for(self._audio_queue.get(), timeout=0.1)
        except asyncio.TimeoutError:
            return b""  # No audio yet, but not done

    async def flush(self) -> None:
        """Signal end of text input. ElevenLabs will generate remaining audio and close."""
        if self._ws and not self._closed:
            # Send empty string to signal end of input
            # ElevenLabs will generate any remaining buffered text,
            # send all audio chunks, send isFinal, then close the connection
            self._logger.info(
                "ElevenLabsStreamingSynthesizer: sending end-of-input (empty string)"
            )
            await self._ws.send_str(json.dumps({"text": ""}))
            self._logger.info("ElevenLabsStreamingSynthesizer: end-of-input sent")
        else:
            self._logger.warning(
                f"ElevenLabsStreamingSynthesizer: skipping flush - "
                f"ws={self._ws is not None}, closed={self._closed}"
            )

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


# Valid ElevenLabs model IDs
ELEVENLABS_STT_MODELS = {"scribe_v1", "scribe_v2_realtime"}
ELEVENLABS_TTS_MODELS = {
    "eleven_multilingual_v2",
    "eleven_turbo_v2_5",
    "eleven_monolingual_v1",
    "eleven_flash_v2_5",
    "eleven_flash_v2",
}


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
        # Validate and default models - use valid ElevenLabs model IDs
        self.stt_model = (
            stt_model if stt_model in ELEVENLABS_STT_MODELS else "scribe_v1"
        )
        self.tts_model = (
            tts_model
            if tts_model in ELEVENLABS_TTS_MODELS
            else "eleven_multilingual_v2"
        )
        self.default_voice = default_voice

    async def transcribe(self, audio_data: bytes, audio_format: str) -> str:
        """
        Transcribe audio using ElevenLabs Speech-to-Text API.

        Args:
            audio_data: Raw audio bytes
            audio_format: Format of the audio (e.g., 'webm', 'mp3', 'wav')

        Returns:
            Transcribed text
        """
        if not self.api_key:
            raise ValueError("ElevenLabs API key required for transcription")

        from onyx.utils.logger import setup_logger

        logger = setup_logger()

        url = f"{self.api_base}/v1/speech-to-text"

        # Map common formats to MIME types
        mime_types = {
            "webm": "audio/webm",
            "mp3": "audio/mpeg",
            "wav": "audio/wav",
            "ogg": "audio/ogg",
            "flac": "audio/flac",
            "m4a": "audio/mp4",
        }
        mime_type = mime_types.get(audio_format.lower(), f"audio/{audio_format}")

        headers = {
            "xi-api-key": self.api_key,
        }

        # ElevenLabs expects multipart form data
        form_data = aiohttp.FormData()
        form_data.add_field(
            "audio",
            audio_data,
            filename=f"audio.{audio_format}",
            content_type=mime_type,
        )
        # For batch STT, use scribe_v1 (not the realtime model)
        batch_model = (
            self.stt_model if self.stt_model in ("scribe_v1",) else "scribe_v1"
        )
        form_data.add_field("model_id", batch_model)

        logger.info(
            f"ElevenLabs transcribe: sending {len(audio_data)} bytes, format={audio_format}"
        )

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, data=form_data) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"ElevenLabs transcribe failed: {error_text}")
                    raise RuntimeError(f"ElevenLabs transcription failed: {error_text}")

                result = await response.json()
                text = result.get("text", "")
                logger.info(f"ElevenLabs transcribe: got result: {text[:50]}...")
                return text

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
        from onyx.utils.logger import setup_logger

        logger = setup_logger()

        if not self.api_key:
            raise ValueError("ElevenLabs API key required for TTS")

        voice_id = voice or self.default_voice or "21m00Tcm4TlvDq8ikWAM"  # Rachel

        url = f"{self.api_base}/v1/text-to-speech/{voice_id}/stream"

        logger.info(
            f"ElevenLabs TTS: starting synthesis, text='{text[:50]}...', "
            f"voice={voice_id}, model={self.tts_model}"
        )

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
                logger.info(
                    f"ElevenLabs TTS: got response status={response.status}, "
                    f"content-type={response.headers.get('content-type')}"
                )
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"ElevenLabs TTS failed: {error_text}")
                    raise RuntimeError(f"ElevenLabs TTS failed: {error_text}")

                # Use 8192 byte chunks for smoother streaming
                chunk_count = 0
                total_bytes = 0
                async for chunk in response.content.iter_chunked(8192):
                    if chunk:
                        chunk_count += 1
                        total_bytes += len(chunk)
                        yield chunk
                logger.info(
                    f"ElevenLabs TTS: streaming complete, {chunk_count} chunks, "
                    f"{total_bytes} total bytes"
                )

    def get_available_voices(self) -> list[dict[str, str]]:
        """Return common ElevenLabs voices."""
        return ELEVENLABS_VOICES.copy()

    def get_available_stt_models(self) -> list[dict[str, str]]:
        return [
            {"id": "scribe_v2_realtime", "name": "Scribe v2 Realtime (Streaming)"},
            {"id": "scribe_v1", "name": "Scribe v1 (Batch)"},
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
        # ElevenLabs realtime STT requires scribe_v2_realtime model
        # Frontend sends PCM16 at 24kHz, but ElevenLabs expects 16kHz
        # The transcriber will resample automatically
        transcriber = ElevenLabsStreamingTranscriber(
            api_key=self.api_key,
            model="scribe_v2_realtime",
            input_sample_rate=24000,  # What frontend sends
            target_sample_rate=16000,  # What ElevenLabs expects
            language_code="en",
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
            model_id=self.tts_model,
            # Use mp3_44100_64 for streaming - good balance of quality and chunk size
            output_format="mp3_44100_64",
        )
        await synthesizer.connect()
        return synthesizer
