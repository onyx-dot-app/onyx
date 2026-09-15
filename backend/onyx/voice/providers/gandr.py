"""Gandr voice provider for TTS.

Gandr exposes an OpenAI compatible speech endpoint:
- **TTS**: `POST /v1/audio/speech` with a JSON body of `model`, `input`,
  `voice`, and `response_format`. The response body streams audio.
  Output formats are mp3 (default), wav, and pcm; pcm is headerless
  s16le mono at 24000 Hz. Input is capped at 2000 characters per request.
- **STT**: not offered. The transcription methods raise.

Voices: gandr-mia, gandr-ava, gandr-jenny, gandr-dane, gandr-leo,
gandr-lewis. The service covers 23 languages, and every render is
watermarked.

API keys are issued at https://gandr.ai.
"""

import asyncio
from collections.abc import AsyncIterator

import aiohttp

from onyx.tracing.flows import LLMFlow
from onyx.tracing.llm_utils import traced_llm_call
from onyx.voice.interface import (
    StreamingSynthesizerProtocol,
    VoiceProviderInterface,
)

# Default Gandr API base URL
DEFAULT_GANDR_API_BASE = "https://tts.gandr.ai"

# Gandr caps speech input at 2000 characters per request.
GANDR_MAX_INPUT_CHARACTERS = 2000

# Gandr available voices for TTS
GANDR_VOICES = [
    {"id": "gandr-mia", "name": "Mia"},
    {"id": "gandr-ava", "name": "Ava"},
    {"id": "gandr-jenny", "name": "Jenny"},
    {"id": "gandr-dane", "name": "Dane"},
    {"id": "gandr-leo", "name": "Leo"},
    {"id": "gandr-lewis", "name": "Lewis"},
]

# Valid Gandr TTS model IDs
GANDR_TTS_MODELS = {"tts-1"}


def _validate_input_length(text: str) -> None:
    """Reject input over the Gandr per-request character cap.

    The cap is validated client side so callers get a clear error instead
    of a rejected HTTP request.
    """
    if len(text) > GANDR_MAX_INPUT_CHARACTERS:
        raise ValueError(
            f"Gandr TTS accepts at most {GANDR_MAX_INPUT_CHARACTERS} characters "
            f"per request, got {len(text)}. Split the text and synthesize it "
            "in parts."
        )


class GandrStreamingSynthesizer(StreamingSynthesizerProtocol):
    """Streaming TTS using the Gandr HTTP speech API with streaming responses."""

    def __init__(
        self,
        api_key: str,
        voice: str = "gandr-mia",
        model: str = "tts-1",
        api_base: str | None = None,
    ):
        from onyx.utils.logger import setup_logger

        self._logger = setup_logger()
        self.api_key = api_key
        self.voice = voice
        self.model = model
        self.api_base = api_base or DEFAULT_GANDR_API_BASE
        self._session: aiohttp.ClientSession | None = None
        self._audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._text_queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._synthesis_task: asyncio.Task | None = None
        self._closed = False
        self._flushed = False

    async def connect(self) -> None:
        """Initialize HTTP session for TTS requests."""
        self._logger.info("GandrStreamingSynthesizer: connecting")
        self._session = aiohttp.ClientSession()
        # Start background task to process text queue
        self._synthesis_task = asyncio.create_task(self._process_text_queue())
        self._logger.info("GandrStreamingSynthesizer: connected")

    async def _process_text_queue(self) -> None:
        """Background task to process queued text for synthesis."""
        while not self._closed:
            try:
                text = await asyncio.wait_for(self._text_queue.get(), timeout=0.1)
                if text is None:
                    break
                await self._synthesize_text(text)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._logger.error("Error processing text queue: %s", e)

    async def _synthesize_text(self, text: str) -> None:
        """Make an HTTP TTS request and stream audio to the queue."""
        if not self._session or self._closed:
            return

        url = f"{self.api_base.rstrip('/')}/v1/audio/speech"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        # The Gandr speech endpoint takes exactly these fields.
        payload = {
            "model": self.model,
            "input": text,
            "voice": self.voice,
            "response_format": "mp3",
        }

        try:
            async with self._session.post(
                url, headers=headers, json=payload
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    self._logger.error("Gandr TTS error: %s", error_text)
                    return

                # Use 8192 byte chunks so MP3 frames arrive mostly complete
                # for playback.
                async for chunk in response.content.iter_chunked(8192):
                    if self._closed:
                        break
                    if chunk:
                        await self._audio_queue.put(chunk)
        except Exception as e:
            self._logger.error("GandrStreamingSynthesizer synthesis error: %s", e)

    async def send_text(self, text: str) -> None:
        """Queue text to be synthesized via HTTP streaming.

        Each queued piece of text becomes one request, so each piece must
        stay within the Gandr per-request character cap.
        """
        if not text.strip() or self._closed:
            return
        _validate_input_length(text)
        await self._text_queue.put(text)

    async def receive_audio(self) -> bytes | None:
        """Receive next audio chunk (MP3 format)."""
        try:
            return await asyncio.wait_for(self._audio_queue.get(), timeout=0.1)
        except asyncio.TimeoutError:
            return b""  # No audio yet, but not done

    async def flush(self) -> None:
        """Signal end of text input, then wait for synthesis to complete."""
        if self._flushed:
            return
        self._flushed = True

        # Signal end of text input
        await self._text_queue.put(None)

        # Wait for synthesis task to complete processing all text
        if self._synthesis_task and not self._synthesis_task.done():
            try:
                await asyncio.wait_for(self._synthesis_task, timeout=60.0)
            except asyncio.TimeoutError:
                self._logger.warning("GandrStreamingSynthesizer: flush timeout")
                self._synthesis_task.cancel()
                try:
                    await self._synthesis_task
                except asyncio.CancelledError:
                    pass
            except asyncio.CancelledError:
                pass

        # Signal end of audio stream
        await self._audio_queue.put(None)

    async def close(self) -> None:
        """Close the session."""
        if self._closed:
            return
        self._closed = True

        # Signal end of queues only if flush wasn't already called
        if not self._flushed:
            await self._text_queue.put(None)
            await self._audio_queue.put(None)

        if self._synthesis_task and not self._synthesis_task.done():
            self._synthesis_task.cancel()
            try:
                await self._synthesis_task
            except asyncio.CancelledError:
                pass

        if self._session:
            await self._session.close()


class GandrVoiceProvider(VoiceProviderInterface):
    """Gandr voice provider. TTS only, no STT."""

    def __init__(
        self,
        api_key: str | None,
        api_base: str | None = None,
        stt_model: str | None = None,
        tts_model: str | None = None,
        default_voice: str | None = None,
    ):
        self.api_key = api_key
        self.api_base = api_base or DEFAULT_GANDR_API_BASE
        # Gandr has no STT models; the field is kept for interface parity.
        self.stt_model = stt_model
        # Validate and default the model, matching the other providers.
        self.tts_model = tts_model if tts_model in GANDR_TTS_MODELS else "tts-1"
        self.default_voice = default_voice or "gandr-mia"

    async def transcribe(self, audio_data: bytes, audio_format: str) -> str:
        """Gandr is a text to speech provider and does not offer STT."""
        raise NotImplementedError(
            "Gandr does not support transcription. Configure a different "
            "provider for STT."
        )

    async def synthesize_stream(
        self, text: str, voice: str | None = None, speed: float = 1.0
    ) -> AsyncIterator[bytes]:
        """
        Convert text to audio using Gandr TTS with streaming.

        Args:
            text: Text to convert to speech, at most 2000 characters
            voice: Voice ID (defaults to provider's default voice or gandr-mia)
            speed: Accepted for interface compatibility. The Gandr request
                body carries only model, input, voice, and response_format,
                so this value is not forwarded.

        Yields:
            Audio data chunks (mp3 format)
        """
        from onyx.utils.logger import setup_logger

        logger = setup_logger()

        if not self.api_key:
            raise ValueError("Gandr API key required for TTS")

        _validate_input_length(text)

        voice_id = voice or self.default_voice or "gandr-mia"

        url = f"{self.api_base.rstrip('/')}/v1/audio/speech"

        logger.info(
            "Gandr TTS: starting synthesis, text='%s...', voice=%s, model=%s",
            text[:50],
            voice_id,
            self.tts_model,
        )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.tts_model,
            "input": text,
            "voice": voice_id,
            "response_format": "mp3",
        }

        with traced_llm_call(
            flow=LLMFlow.TTS,
            model=self.tts_model,
            provider="gandr",
            input_messages=[{"role": "user", "content": text}],
        ):
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload) as response:
                    logger.info(
                        "Gandr TTS: got response status=%s, content-type=%s",
                        response.status,
                        response.headers.get("content-type"),
                    )
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error("Gandr TTS failed: %s", error_text)
                        raise RuntimeError(f"Gandr TTS failed: {error_text}")

                    # Use 8192 byte chunks so MP3 frames arrive mostly complete
                    chunk_count = 0
                    total_bytes = 0
                    async for chunk in response.content.iter_chunked(8192):
                        if chunk:
                            chunk_count += 1
                            total_bytes += len(chunk)
                            yield chunk
                    logger.info(
                        "Gandr TTS: streaming complete, %s chunks, %s total bytes",
                        chunk_count,
                        total_bytes,
                    )

    async def validate_credentials(self) -> None:
        """Validate the Gandr API key.

        Gandr's public API surface is the speech endpoint itself, so this
        issues a minimal synthesis request and checks the response status.
        Note that this performs a real synthesis request.
        """
        if not self.api_key:
            raise ValueError("Gandr API key required")

        url = f"{self.api_base.rstrip('/')}/v1/audio/speech"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.tts_model,
            "input": "Hello.",
            "voice": self.default_voice or "gandr-mia",
            "response_format": "mp3",
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status == 200:
                    return
                if response.status in (401, 403):
                    raise RuntimeError("Invalid Gandr API key.")
                raise RuntimeError("Gandr credential validation failed.")

    def get_available_voices(self) -> list[dict[str, str]]:
        """Return the Gandr voices."""
        return GANDR_VOICES.copy()

    def get_available_stt_models(self) -> list[dict[str, str]]:
        """Gandr has no STT models."""
        return []

    def get_available_tts_models(self) -> list[dict[str, str]]:
        return [
            {"id": "tts-1", "name": "Gandr TTS"},
        ]

    def supports_streaming_tts(self) -> bool:
        """Gandr supports streaming TTS via HTTP streaming responses."""
        return True

    async def create_streaming_synthesizer(
        self, voice: str | None = None, speed: float = 1.0
    ) -> GandrStreamingSynthesizer:
        """Create a streaming TTS session using the HTTP streaming API.

        The speed argument is accepted for interface compatibility and is
        not forwarded; the Gandr request body carries only model, input,
        voice, and response_format.
        """
        if not self.api_key:
            raise ValueError("API key required for streaming TTS")
        synthesizer = GandrStreamingSynthesizer(
            api_key=self.api_key,
            voice=voice or self.default_voice or "gandr-mia",
            model=self.tts_model or "tts-1",
            api_base=self.api_base,
        )
        await synthesizer.connect()
        return synthesizer
