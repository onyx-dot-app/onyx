"""Zoom AI Services Scribe voice provider.

Zoom currently provides Live streaming STT for Onyx voice mode. The Fast API
requires a public media URL, so Onyx uses the Live WebSocket endpoint only.
"""

import asyncio
import json
import time
from collections.abc import AsyncIterator
from enum import StrEnum
from typing import Any

import aiohttp
import jwt

from onyx.tracing.flows import LLMFlow
from onyx.tracing.llm_utils import traced_llm_call
from onyx.utils.logger import setup_logger
from onyx.voice.audio_utils import resample_pcm16
from onyx.voice.interface import (
    StreamingTranscriberProtocol,
    TranscriptResult,
    VoiceProviderInterface,
)

logger = setup_logger()

ZOOM_API_BASE = "https://api.zoom.us"
ZOOM_SCRIBE_LIVE_PATH = "/v2/aiservices/scribe/live"
ZOOM_WS_SUBPROTOCOL = "live-asr"
ZOOM_INPUT_SAMPLE_RATE = 24000
ZOOM_TARGET_SAMPLE_RATE = 16000
ZOOM_FRAME_BYTES = 3200
ZOOM_TRANSCRIBE_SEND_CHUNK_BYTES = ZOOM_INPUT_SAMPLE_RATE * 2
ZOOM_JWT_TTL_SECONDS = 15 * 60
ZOOM_JWT_IAT_SKEW_SECONDS = 30
ZOOM_HANDSHAKE_TIMEOUT_SECONDS = 10.0
ZOOM_CLOSE_DRAIN_SECONDS = 3.0
ZOOM_STT_MODEL = "scribe-live"

ZOOM_SUPPORTED_LANGUAGES = frozenset(
    {
        "en-US",
        "zh-CN",
        "ja-JP",
        "es-ES",
        "it-IT",
        "fr-FR",
        "de-DE",
        "ar-SA",
        "ar-AE",
        "pt-BR",
        "pt-PT",
    }
)
ZOOM_DEFAULT_LANGUAGE = "en-US"


class ZoomScribeMessageType(StrEnum):
    SESSION_CREATED = "session.created"
    SESSION_UPDATED = "session.updated"
    SPEECH_STARTED = "input_audio_buffer.speech_started"
    SPEECH_STOPPED = "input_audio_buffer.speech_stopped"
    TRANSCRIPTION_COMPLETED = "transcription.completed"
    ERROR = "error"
    SESSION_CLOSED = "session.closed"


def _http_to_ws_url(http_url: str) -> str:
    if http_url.startswith("https://"):
        return "wss://" + http_url[8:]
    if http_url.startswith("http://"):
        return "ws://" + http_url[7:]
    return http_url


def build_zoom_scribe_jwt(api_key: str, api_secret: str, now: int | None = None) -> str:
    issued_at = int(time.time()) if now is None else now
    claims: dict[str, int | str] = {
        "iss": api_key,
        "iat": issued_at - ZOOM_JWT_IAT_SKEW_SECONDS,
        "exp": issued_at + ZOOM_JWT_TTL_SECONDS,
    }
    return jwt.encode(claims, api_secret, algorithm="HS256")


def _normalize_language(custom_config: dict[str, Any] | None) -> str:
    language = (custom_config or {}).get("language", ZOOM_DEFAULT_LANGUAGE)
    if not isinstance(language, str):
        raise ValueError("Zoom language must be a string.")
    if language not in ZOOM_SUPPORTED_LANGUAGES:
        supported = ", ".join(sorted(ZOOM_SUPPORTED_LANGUAGES))
        raise ValueError(
            f"Unsupported Zoom language {language!r}. Use one of: {supported}."
        )
    return language


class ZoomStreamingTranscriber(StreamingTranscriberProtocol):
    """Streaming transcription session using Zoom Scribe Live."""

    def __init__(
        self,
        api_key: str | None,
        api_secret: str | None,
        language: str = ZOOM_DEFAULT_LANGUAGE,
        api_base: str | None = None,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.language = language
        self.api_base = api_base or ZOOM_API_BASE
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._receive_task: asyncio.Task[None] | None = None
        self._transcript_queue: asyncio.Queue[TranscriptResult | None] = asyncio.Queue()
        self._handshake_event = asyncio.Event()
        self._handshake_error: Exception | None = None
        self._close_event = asyncio.Event()
        self._buffer = bytearray()
        self._accumulated_transcript = ""
        self._closed = False
        self._error_signaled = False

    async def connect(self) -> None:
        if not self.api_key or not self.api_secret:
            raise ValueError(
                "Zoom API key and API secret are required for streaming STT."
            )

        self._session = aiohttp.ClientSession()
        ws_base = _http_to_ws_url(self.api_base.rstrip("/"))
        token = build_zoom_scribe_jwt(self.api_key, self.api_secret)
        try:
            self._ws = await self._session.ws_connect(
                f"{ws_base}{ZOOM_SCRIBE_LIVE_PATH}",
                headers={"Authorization": f"Bearer {token}"},
                protocols=[ZOOM_WS_SUBPROTOCOL],
            )
            await self._ws.send_str(
                json.dumps(
                    {
                        "type": "session.update",
                        "language": self.language,
                        "audio": {"format": "pcm16"},
                    }
                )
            )
            self._receive_task = asyncio.create_task(self._receive_loop())
            await asyncio.wait_for(
                self._handshake_event.wait(), timeout=ZOOM_HANDSHAKE_TIMEOUT_SECONDS
            )
            if self._handshake_error:
                raise self._handshake_error
        except asyncio.CancelledError:
            await self._cleanup()
            raise
        except Exception:
            await self._cleanup()
            raise

    async def _receive_loop(self) -> None:
        if not self._ws:
            await self._transcript_queue.put(None)
            return

        try:
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    if await self._handle_text_message(msg.data):
                        break
                    continue
                if msg.type == aiohttp.WSMsgType.BINARY:
                    logger.debug(
                        "Zoom Scribe returned binary payload (%s bytes)", len(msg.data)
                    )
                    continue
                if msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED):
                    if not self._handshake_event.is_set():
                        self._handshake_error = RuntimeError(
                            "Zoom Scribe stream closed before setup completed."
                        )
                    if not self._closed and not self._error_signaled:
                        await self._signal_error("Zoom Scribe closed the stream.")
                    break
                if msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error("Zoom Scribe WebSocket error")
                    if not self._handshake_event.is_set():
                        self._handshake_error = RuntimeError(
                            "Zoom Scribe stream failed before setup completed."
                        )
                    await self._signal_error("Zoom Scribe stream failed.")
                    break
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.error("Zoom Scribe receive loop failed", exc_info=True)
            await self._signal_error("Zoom Scribe stream failed.")
        finally:
            self._close_event.set()
            if not self._handshake_event.is_set():
                self._handshake_error = self._handshake_error or RuntimeError(
                    "Zoom Scribe stream ended before setup completed."
                )
                self._handshake_event.set()
            await self._transcript_queue.put(None)

    async def _handle_text_message(self, raw_data: str) -> bool:
        try:
            parsed: Any = json.loads(raw_data)
        except json.JSONDecodeError:
            logger.error("Zoom Scribe returned non-JSON text payload")
            return False
        if not isinstance(parsed, dict):
            logger.error("Zoom Scribe returned non-object JSON payload")
            return False

        msg_type = parsed.get("type")
        if msg_type == ZoomScribeMessageType.SESSION_UPDATED:
            self._handshake_event.set()
            return False
        if msg_type == ZoomScribeMessageType.TRANSCRIPTION_COMPLETED:
            await self._handle_transcription_completed(parsed)
            return False
        if msg_type == ZoomScribeMessageType.ERROR:
            error = parsed.get("error")
            fatal = True
            if isinstance(error, dict):
                fatal = error.get("fatal") is not False
            logger.error("Zoom Scribe returned an error event (fatal=%s)", fatal)
            if not fatal:
                return False
            if not self._handshake_event.is_set():
                self._handshake_error = RuntimeError(
                    "Zoom Scribe rejected the streaming session."
                )
                self._handshake_event.set()
            await self._signal_error("Zoom Scribe stream failed.")
            return True
        if msg_type == ZoomScribeMessageType.SESSION_CLOSED:
            self._close_event.set()
            return True
        if msg_type in {
            ZoomScribeMessageType.SESSION_CREATED,
            ZoomScribeMessageType.SPEECH_STARTED,
            ZoomScribeMessageType.SPEECH_STOPPED,
        }:
            return False
        logger.debug("Zoom Scribe returned unhandled event type: %s", msg_type)
        return False

    async def _handle_transcription_completed(self, data: dict[str, Any]) -> None:
        transcript = data.get("transcript")
        if not isinstance(transcript, str) or not transcript.strip():
            return
        text = transcript.strip()
        self._accumulated_transcript = (
            f"{self._accumulated_transcript} {text}"
            if self._accumulated_transcript
            else text
        )
        await self._transcript_queue.put(
            TranscriptResult(text=self._accumulated_transcript, is_vad_end=True)
        )

    async def _signal_error(self, message: str) -> None:
        if self._error_signaled:
            return
        self._error_signaled = True
        await self._transcript_queue.put(
            TranscriptResult(
                text=self._accumulated_transcript,
                is_vad_end=True,
                error=message,
            )
        )

    async def send_audio(self, chunk: bytes) -> None:
        if not self._ws or self._closed or self._ws.closed:
            raise RuntimeError("Zoom Scribe streaming session is not connected.")

        resampled = resample_pcm16(
            chunk, ZOOM_INPUT_SAMPLE_RATE, ZOOM_TARGET_SAMPLE_RATE
        )
        self._buffer.extend(resampled)
        while len(self._buffer) >= ZOOM_FRAME_BYTES:
            frame = bytes(self._buffer[:ZOOM_FRAME_BYTES])
            del self._buffer[:ZOOM_FRAME_BYTES]
            await self._ws.send_bytes(frame)

    async def receive_transcript(self) -> TranscriptResult | None:
        try:
            return await asyncio.wait_for(self._transcript_queue.get(), timeout=0.1)
        except asyncio.TimeoutError:
            return TranscriptResult(text="", is_vad_end=False)

    async def close(self) -> str:
        if self._closed:
            return self._accumulated_transcript
        self._closed = True
        try:
            if not self._ws or self._ws.closed:
                return self._accumulated_transcript
            try:
                if self._buffer:
                    await self._ws.send_bytes(bytes(self._buffer))
                    self._buffer.clear()
                await self._ws.send_str(json.dumps({"type": "session.close"}))
                await asyncio.wait_for(
                    self._close_event.wait(), timeout=ZOOM_CLOSE_DRAIN_SECONDS
                )
            except asyncio.TimeoutError:
                logger.warning("Timed out waiting for Zoom Scribe session close.")
            except Exception:
                logger.debug("Zoom Scribe session close request failed", exc_info=True)
            return self._accumulated_transcript
        finally:
            await self._cleanup()

    async def _cleanup(self) -> None:
        if self._receive_task and not self._receive_task.done():
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.debug("Zoom Scribe receive task cleanup failed", exc_info=True)
        if self._ws and not self._ws.closed:
            try:
                await self._ws.close()
            except Exception:
                logger.debug("Zoom Scribe WebSocket cleanup failed", exc_info=True)
        if self._session and not self._session.closed:
            try:
                await self._session.close()
            except Exception:
                logger.debug("Zoom Scribe session cleanup failed", exc_info=True)

    def reset_transcript(self) -> None:
        self._accumulated_transcript = ""


class ZoomVoiceProvider(VoiceProviderInterface):
    """Zoom Scribe provider for streaming and short-session PCM16 STT."""

    def __init__(
        self,
        api_key: str | None,
        api_secret: str | None = None,
        custom_config: dict[str, Any] | None = None,
        stt_model: str | None = None,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.custom_config = custom_config or {}
        self.language = _normalize_language(self.custom_config)
        if stt_model is not None and stt_model != ZOOM_STT_MODEL:
            raise ValueError("Zoom Scribe STT model must be 'scribe-live'.")
        self.stt_model = ZOOM_STT_MODEL

    async def transcribe(self, audio_data: bytes, audio_format: str) -> str:
        if audio_format.lower() != "pcm16":
            raise ValueError("Zoom Scribe only supports pcm16 audio in Onyx.")
        if not self.api_key or not self.api_secret:
            raise ValueError("Zoom API key and API secret are required for STT.")

        transcriber = ZoomStreamingTranscriber(
            api_key=self.api_key,
            api_secret=self.api_secret,
            language=self.language,
        )
        with traced_llm_call(
            flow=LLMFlow.STT,
            model=ZOOM_STT_MODEL,
            provider="zoom",
        ):
            await transcriber.connect()
            closed = False
            try:
                for offset in range(
                    0, len(audio_data), ZOOM_TRANSCRIBE_SEND_CHUNK_BYTES
                ):
                    await transcriber.send_audio(
                        audio_data[offset : offset + ZOOM_TRANSCRIBE_SEND_CHUNK_BYTES]
                    )
                transcript = await transcriber.close()
                closed = True
                return transcript
            finally:
                if not closed:
                    try:
                        await transcriber.close()
                    except Exception:
                        logger.debug(
                            "Zoom Scribe transcriber close failed", exc_info=True
                        )

    async def synthesize_stream(
        self, text: str, voice: str | None = None, speed: float = 1.0
    ) -> AsyncIterator[bytes]:
        _ = (text, voice, speed)
        raise NotImplementedError("Zoom Scribe does not support TTS in Onyx.")
        yield b""

    async def validate_credentials(self) -> None:
        if not self.api_key or not self.api_secret:
            raise ValueError("Zoom API key and API secret are required.")
        transcriber = ZoomStreamingTranscriber(
            api_key=self.api_key,
            api_secret=self.api_secret,
            language=self.language,
        )
        await transcriber.connect()
        closed = False
        try:
            return None
        finally:
            if not closed:
                try:
                    await transcriber.close()
                    closed = True
                except Exception:
                    logger.debug(
                        "Zoom Scribe credential validation close failed", exc_info=True
                    )

    def get_available_voices(self) -> list[dict[str, str]]:
        return []

    def get_available_stt_models(self) -> list[dict[str, str]]:
        return [{"id": ZOOM_STT_MODEL, "name": "Zoom Scribe Live"}]

    def get_available_tts_models(self) -> list[dict[str, str]]:
        return []

    def supports_streaming_stt(self) -> bool:
        return True

    def supports_streaming_tts(self) -> bool:
        return False

    def allows_streaming_stt_fallback(self) -> bool:
        return False

    async def create_streaming_transcriber(  # ty: ignore[invalid-method-override]
        self, _audio_format: str = "pcm16"
    ) -> ZoomStreamingTranscriber:
        if not self.api_key or not self.api_secret:
            raise ValueError(
                "Zoom API key and API secret are required for streaming STT."
            )
        transcriber = ZoomStreamingTranscriber(
            api_key=self.api_key,
            api_secret=self.api_secret,
            language=self.language,
        )
        await transcriber.connect()
        return transcriber
