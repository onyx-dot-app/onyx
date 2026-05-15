import json
import secrets
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi import Depends
from fastapi import File
from fastapi import UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from pydantic import Field
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.db.engine.sql_engine import get_session
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.db.voice import fetch_default_stt_provider
from onyx.db.voice import fetch_default_tts_provider
from onyx.db.voice import update_user_voice_settings
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.redis.redis_pool import store_ws_token
from onyx.redis.redis_pool import WsTokenRateLimitExceeded
from onyx.server.manage.models import VoiceSettingsUpdateRequest
from onyx.utils.logger import setup_logger
from onyx.voice.factory import get_voice_provider

logger = setup_logger()

router = APIRouter(prefix="/voice")

# Max audio file size: 25MB (Whisper limit)
MAX_AUDIO_SIZE = 25 * 1024 * 1024
# Chunk size for streaming uploads (8KB)
UPLOAD_READ_CHUNK_SIZE = 8192


class VoiceStatusResponse(BaseModel):
    stt_enabled: bool
    tts_enabled: bool


@router.get("/status")
def get_voice_status(
    _: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> VoiceStatusResponse:
    """Check whether STT and TTS providers are configured and ready."""
    stt_provider = fetch_default_stt_provider(db_session)
    tts_provider = fetch_default_tts_provider(db_session)
    return VoiceStatusResponse(
        stt_enabled=stt_provider is not None and stt_provider.api_key is not None,
        tts_enabled=tts_provider is not None and tts_provider.api_key is not None,
    )


@router.post("/transcribe")
async def transcribe_audio(
    audio: UploadFile = File(...),
    _: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> dict[str, str]:
    """Transcribe audio to text using the default STT provider."""
    provider_db = fetch_default_stt_provider(db_session)
    if provider_db is None:
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            "No speech-to-text provider configured. Please contact your administrator.",
        )

    if not provider_db.api_key:
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            "Voice provider API key not configured.",
        )

    # Read in chunks to enforce size limit during streaming (prevents OOM attacks)
    chunks: list[bytes] = []
    total = 0
    while chunk := await audio.read(UPLOAD_READ_CHUNK_SIZE):
        total += len(chunk)
        if total > MAX_AUDIO_SIZE:
            raise OnyxError(
                OnyxErrorCode.PAYLOAD_TOO_LARGE,
                f"Audio file too large. Maximum size is {MAX_AUDIO_SIZE // (1024 * 1024)}MB.",
            )
        chunks.append(chunk)
    audio_data = b"".join(chunks)

    # Extract format from filename
    filename = audio.filename or "audio.webm"
    audio_format = filename.rsplit(".", 1)[-1] if "." in filename else "webm"

    try:
        provider = get_voice_provider(provider_db)
    except ValueError as exc:
        raise OnyxError(OnyxErrorCode.INTERNAL_ERROR, str(exc)) from exc

    try:
        text = await provider.transcribe(audio_data, audio_format)
        return {"text": text}
    except NotImplementedError as exc:
        raise OnyxError(
            OnyxErrorCode.NOT_IMPLEMENTED,
            f"Speech-to-text not implemented for {provider_db.provider_type}.",
        ) from exc
    except Exception as exc:
        logger.error("Transcription failed: %s", exc)
        raise OnyxError(
            OnyxErrorCode.INTERNAL_ERROR,
            "Transcription failed. Please try again.",
        ) from exc


def _extract_provider_error(exc: Exception) -> str:
    """Extract a human-readable message from a provider exception.

    Provider errors often embed JSON from upstream APIs (e.g. ElevenLabs).
    This tries to parse a readable ``message`` field out of common JSON
    error shapes; falls back to ``str(exc)`` if nothing better is found.
    """
    raw = str(exc)
    try:
        # Many providers embed JSON after a prefix like "ElevenLabs TTS failed: {...}"
        json_start = raw.find("{")
        if json_start == -1:
            return raw
        parsed = json.loads(raw[json_start:])
        # Shape: {"detail": {"message": "..."}} (ElevenLabs)
        detail = parsed.get("detail", parsed)
        if isinstance(detail, dict):
            return detail.get("message") or detail.get("error") or raw
        if isinstance(detail, str):
            return detail
    except (json.JSONDecodeError, AttributeError, TypeError):
        pass
    return raw


class SynthesizeRequest(BaseModel):
    text: str = Field(..., min_length=1)
    voice: str | None = None
    speed: float | None = Field(default=None, ge=0.5, le=2.0)


@router.post("/synthesize")
async def synthesize_speech(
    body: SynthesizeRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> StreamingResponse:
    """Synthesize text to speech using the default TTS provider."""
    text = body.text
    voice = body.voice
    speed = body.speed
    logger.info(
        "TTS request: text length=%s, voice=%s, speed=%s", len(text), voice, speed
    )

    # Use short-lived session to fetch provider config, then release connection
    # before starting the long-running streaming response
    with get_session_with_current_tenant() as db_session:
        provider_db = fetch_default_tts_provider(db_session)
        if provider_db is None:
            logger.error("No TTS provider configured")
            raise OnyxError(
                OnyxErrorCode.VALIDATION_ERROR,
                "No text-to-speech provider configured. Please contact your administrator.",
            )

        if not provider_db.api_key:
            logger.error("TTS provider has no API key")
            raise OnyxError(
                OnyxErrorCode.VALIDATION_ERROR,
                "Voice provider API key not configured.",
            )

        # Use request voice or provider default
        final_voice = voice or provider_db.default_voice
        # Use explicit None checks to avoid falsy float issues (0.0 would be skipped with `or`)
        final_speed = (
            speed
            if speed is not None
            else (
                user.voice_playback_speed
                if user.voice_playback_speed is not None
                else 1.0
            )
        )

        logger.info(
            "TTS using provider: %s, voice: %s, speed: %s",
            provider_db.provider_type,
            final_voice,
            final_speed,
        )

        try:
            provider = get_voice_provider(provider_db)
        except ValueError as exc:
            logger.error("Failed to get voice provider: %s", exc)
            raise OnyxError(OnyxErrorCode.INTERNAL_ERROR, str(exc)) from exc

    # Pull the first chunk before returning the StreamingResponse. If the
    # provider rejects the request (e.g. text too long), the error surfaces
    # as a proper HTTP error instead of a broken audio stream.
    stream_iter = provider.synthesize_stream(
        text=text, voice=final_voice, speed=final_speed
    )
    try:
        first_chunk = await stream_iter.__anext__()
    except StopAsyncIteration:
        raise OnyxError(OnyxErrorCode.INTERNAL_ERROR, "TTS provider returned no audio")
    except Exception as exc:
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY, _extract_provider_error(exc)
        ) from exc

    async def audio_stream() -> AsyncIterator[bytes]:
        yield first_chunk
        chunk_count = 1
        async for chunk in stream_iter:
            chunk_count += 1
            yield chunk
        logger.info("TTS streaming complete: %s chunks sent", chunk_count)

    return StreamingResponse(
        audio_stream(),
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": "inline; filename=speech.mp3",
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.patch("/settings")
def update_voice_settings(
    request: VoiceSettingsUpdateRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> dict[str, str]:
    """Update user's voice settings."""
    update_user_voice_settings(
        db_session=db_session,
        user_id=user.id,
        auto_send=request.auto_send,
        auto_playback=request.auto_playback,
        playback_speed=request.playback_speed,
    )
    db_session.commit()
    return {"status": "ok"}


class WSTokenResponse(BaseModel):
    token: str


@router.post("/ws-token")
async def get_ws_token(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> WSTokenResponse:
    """
    Generate a short-lived token for WebSocket authentication.

    This token should be passed as a query parameter when connecting
    to voice WebSocket endpoints (e.g., /voice/transcribe/stream?token=xxx).

    The token expires after 60 seconds and is single-use.
    Rate limited to 10 tokens per minute per user.
    """
    token = secrets.token_urlsafe(32)
    try:
        await store_ws_token(token, str(user.id))
    except WsTokenRateLimitExceeded:
        raise OnyxError(
            OnyxErrorCode.RATE_LIMITED,
            "Too many token requests. Please wait before requesting another.",
        )
    return WSTokenResponse(token=token)
