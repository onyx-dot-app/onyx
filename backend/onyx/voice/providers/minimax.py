"""MiniMax voice provider for TTS.

MiniMax supports:
- **TTS**: HTTP streaming endpoint that returns hex-encoded audio chunks via SSE.
  Supported models: speech-2.8-hd (high quality) and speech-2.8-turbo (fast).

MiniMax does NOT provide a Speech-to-Text (STT) API, so transcription methods
raise NotImplementedError.

See https://platform.minimax.io/docs/api-reference/speech-t2a-http for API reference.
"""

import asyncio
import json
from collections.abc import AsyncIterator

import aiohttp

from onyx.voice.interface import VoiceProviderInterface

# Default MiniMax API base URL
DEFAULT_MINIMAX_API_BASE = "https://api.minimax.io"

# MiniMax available voices for TTS
MINIMAX_VOICES = [
    {"id": "English_Graceful_Lady", "name": "Graceful Lady"},
    {"id": "English_Insightful_Speaker", "name": "Insightful Speaker"},
    {"id": "English_radiant_girl", "name": "Radiant Girl"},
    {"id": "English_Persuasive_Man", "name": "Persuasive Man"},
    {"id": "English_Lucky_Robot", "name": "Lucky Robot"},
    {"id": "English_expressive_narrator", "name": "Expressive Narrator"},
]

# MiniMax available TTS models
MINIMAX_TTS_MODELS = [
    {"id": "speech-2.8-hd", "name": "Speech 2.8 HD (High Quality)"},
    {"id": "speech-2.8-turbo", "name": "Speech 2.8 Turbo (Fast)"},
]


class MiniMaxVoiceProvider(VoiceProviderInterface):
    """MiniMax voice provider using MiniMax TTS API for speech synthesis.

    MiniMax only supports TTS (Text-to-Speech). STT (Speech-to-Text) is not
    available and will raise NotImplementedError.
    """

    def __init__(
        self,
        api_key: str | None,
        api_base: str | None = None,
        stt_model: str | None = None,
        tts_model: str | None = None,
        default_voice: str | None = None,
    ) -> None:
        self.api_key = api_key
        self.api_base = (api_base or DEFAULT_MINIMAX_API_BASE).rstrip("/")
        self.stt_model = stt_model  # Not used - MiniMax has no STT
        self.tts_model = tts_model or "speech-2.8-hd"
        self.default_voice = default_voice or "English_Graceful_Lady"

    async def transcribe(self, audio_data: bytes, audio_format: str) -> str:
        """MiniMax does not support Speech-to-Text."""
        raise NotImplementedError(
            "MiniMax does not provide a Speech-to-Text API. "
            "Please use a different provider (e.g., OpenAI) for transcription."
        )

    async def synthesize_stream(
        self, text: str, voice: str | None = None, speed: float = 1.0
    ) -> AsyncIterator[bytes]:
        """Convert text to audio using MiniMax TTS API with SSE streaming.

        MiniMax returns hex-encoded audio chunks via Server-Sent Events (SSE).
        Each SSE event contains a JSON payload with a `data.audio` field
        containing hex-encoded audio bytes.

        Args:
            text: Text to convert to speech
            voice: Voice identifier (defaults to provider's default voice)
            speed: Playback speed multiplier (0.5 to 2.0)

        Yields:
            Audio data chunks (mp3 format)
        """
        if not self.api_key:
            raise ValueError("API key required for MiniMax TTS")

        url = f"{self.api_base}/v1/t2a_v2"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "model": self.tts_model,
            "text": text,
            "stream": True,
            "voice_setting": {
                "voice_id": voice or self.default_voice,
                "speed": max(0.5, min(2.0, speed)),
                "vol": 1,
                "pitch": 0,
            },
            "audio_setting": {
                "sample_rate": 32000,
                "bitrate": 128000,
                "format": "mp3",
                "channel": 1,
            },
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise RuntimeError(
                        f"MiniMax TTS error ({response.status}): {error_text}"
                    )

                buffer = ""
                async for chunk in response.content.iter_any():
                    buffer += chunk.decode("utf-8", errors="replace")
                    lines = buffer.split("\n")
                    buffer = lines.pop()  # Keep incomplete line in buffer

                    for line in lines:
                        if not line.startswith("data:"):
                            continue
                        json_str = line[5:].strip()
                        if not json_str or json_str == "[DONE]":
                            continue

                        try:
                            event_data = json.loads(json_str)
                        except json.JSONDecodeError:
                            continue

                        hex_audio = (event_data.get("data") or {}).get("audio")
                        if hex_audio:
                            yield bytes.fromhex(hex_audio)

    async def validate_credentials(self) -> None:
        """Validate MiniMax API key by making a lightweight TTS request."""
        if not self.api_key:
            raise RuntimeError("MiniMax API key is not configured.")

        url = f"{self.api_base}/v1/t2a_v2"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "model": self.tts_model,
            "text": "test",
            "stream": False,
            "voice_setting": {
                "voice_id": self.default_voice,
                "speed": 1,
                "vol": 1,
                "pitch": 0,
            },
            "audio_setting": {
                "sample_rate": 32000,
                "bitrate": 128000,
                "format": "mp3",
                "channel": 1,
            },
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status == 401:
                    raise RuntimeError("Invalid MiniMax API key.")
                if response.status != 200:
                    error_text = await response.text()
                    raise RuntimeError(
                        f"MiniMax API validation failed ({response.status}): {error_text}"
                    )
                result = await response.json()
                status_code = (result.get("base_resp") or {}).get("status_code")
                if status_code is not None and status_code != 0:
                    status_msg = (result.get("base_resp") or {}).get(
                        "status_msg", "unknown error"
                    )
                    raise RuntimeError(
                        f"MiniMax API validation failed: {status_msg}"
                    )

    def get_available_voices(self) -> list[dict[str, str]]:
        """Get available MiniMax TTS voices."""
        return MINIMAX_VOICES.copy()

    def get_available_stt_models(self) -> list[dict[str, str]]:
        """MiniMax does not support STT. Returns empty list."""
        return []

    def get_available_tts_models(self) -> list[dict[str, str]]:
        """Get available MiniMax TTS models."""
        return MINIMAX_TTS_MODELS.copy()

    def supports_streaming_stt(self) -> bool:
        """MiniMax does not support streaming STT."""
        return False

    def supports_streaming_tts(self) -> bool:
        """MiniMax supports streaming TTS via SSE."""
        return True

    async def create_streaming_synthesizer(
        self, voice: str | None = None, speed: float = 1.0
    ) -> "MiniMaxStreamingSynthesizer":
        """Create a streaming TTS session using MiniMax SSE API."""
        if not self.api_key:
            raise ValueError("API key required for streaming TTS")
        synthesizer = MiniMaxStreamingSynthesizer(
            api_key=self.api_key,
            voice=voice or self.default_voice,
            model=self.tts_model,
            speed=speed,
            api_base=self.api_base,
        )
        await synthesizer.connect()
        return synthesizer


class MiniMaxStreamingSynthesizer:
    """Streaming TTS using MiniMax HTTP API with SSE responses."""

    def __init__(
        self,
        api_key: str,
        voice: str = "English_Graceful_Lady",
        model: str = "speech-2.8-hd",
        speed: float = 1.0,
        api_base: str | None = None,
    ) -> None:
        from onyx.utils.logger import setup_logger

        self._logger = setup_logger()
        self.api_key = api_key
        self.voice = voice
        self.model = model
        self.speed = max(0.5, min(2.0, speed))
        self.api_base = (api_base or DEFAULT_MINIMAX_API_BASE).rstrip("/")
        self._session: aiohttp.ClientSession | None = None
        self._audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._text_queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._synthesis_task: asyncio.Task[None] | None = None
        self._closed = False
        self._flushed = False

    async def connect(self) -> None:
        """Initialize HTTP session for TTS requests."""
        self._session = aiohttp.ClientSession()
        self._synthesis_task = asyncio.create_task(self._process_text_queue())

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
                self._logger.error(f"Error processing text queue: {e}")

    async def _synthesize_text(self, text: str) -> None:
        """Make HTTP TTS request and stream audio to queue."""
        if not self._session or self._closed:
            return

        url = f"{self.api_base}/v1/t2a_v2"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "model": self.model,
            "text": text,
            "stream": True,
            "voice_setting": {
                "voice_id": self.voice,
                "speed": self.speed,
                "vol": 1,
                "pitch": 0,
            },
            "audio_setting": {
                "sample_rate": 32000,
                "bitrate": 128000,
                "format": "mp3",
                "channel": 1,
            },
        }

        try:
            async with self._session.post(
                url, headers=headers, json=payload
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    self._logger.error(f"MiniMax TTS error: {error_text}")
                    return

                buffer = ""
                async for chunk in response.content.iter_any():
                    if self._closed:
                        break
                    buffer += chunk.decode("utf-8", errors="replace")
                    lines = buffer.split("\n")
                    buffer = lines.pop()

                    for line in lines:
                        if not line.startswith("data:"):
                            continue
                        json_str = line[5:].strip()
                        if not json_str or json_str == "[DONE]":
                            continue

                        try:
                            event_data = json.loads(json_str)
                        except json.JSONDecodeError:
                            continue

                        hex_audio = (event_data.get("data") or {}).get("audio")
                        status = (event_data.get("data") or {}).get("status")
                        if hex_audio and status != 2:
                            # status 1 = in progress (stream chunks)
                            # status 2 = complete (contains full audio, skip to
                            #             avoid duplicate data in streaming mode)
                            await self._audio_queue.put(bytes.fromhex(hex_audio))
        except Exception as e:
            self._logger.error(f"MiniMaxStreamingSynthesizer synthesis error: {e}")

    async def send_text(self, text: str) -> None:
        """Queue text to be synthesized via HTTP streaming."""
        if not text.strip() or self._closed:
            return
        await self._text_queue.put(text)

    async def receive_audio(self) -> bytes | None:
        """Receive next audio chunk (MP3 format)."""
        try:
            return await asyncio.wait_for(self._audio_queue.get(), timeout=0.1)
        except asyncio.TimeoutError:
            return b""

    async def flush(self) -> None:
        """Signal end of text input - wait for synthesis to complete."""
        if self._flushed:
            return
        self._flushed = True

        await self._text_queue.put(None)

        if self._synthesis_task and not self._synthesis_task.done():
            try:
                await asyncio.wait_for(self._synthesis_task, timeout=60.0)
            except asyncio.TimeoutError:
                self._logger.warning("MiniMaxStreamingSynthesizer: flush timeout")
                self._synthesis_task.cancel()
                try:
                    await self._synthesis_task
                except asyncio.CancelledError:
                    pass
            except asyncio.CancelledError:
                pass

        await self._audio_queue.put(None)

    async def close(self) -> None:
        """Close the session."""
        if self._closed:
            return
        self._closed = True

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
