import secrets
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi import Depends
from fastapi import File
from fastapi import Query
from fastapi import UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
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
        logger.error(f"Transcription failed: {exc}")
        raise OnyxError(
            OnyxErrorCode.INTERNAL_ERROR,
            "Transcription failed. Please try again.",
        ) from exc


@router.post("/synthesize")
async def synthesize_speech(
    text: str | None = Query(
        default=None, description="Text to synthesize", max_length=4096
    ),
    voice: str | None = Query(default=None, description="Voice ID to use"),
    speed: float | None = Query(
        default=None, description="Playback speed (0.5-2.0)", ge=0.5, le=2.0
    ),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> StreamingResponse:
    """
    Synthesize text to speech using the default TTS provider.

    Accepts parameters via query string for streaming compatibility.
    """
    logger.info(
        f"TTS request: text length={len(text) if text else 0}, voice={voice}, speed={speed}"
    )

    if not text:
        raise OnyxError(OnyxErrorCode.VALIDATION_ERROR, "Text is required")

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
            f"TTS using provider: {provider_db.provider_type}, voice: {final_voice}, speed: {final_speed}"
        )

        try:
            provider = get_voice_provider(provider_db)
        except ValueError as exc:
            logger.error(f"Failed to get voice provider: {exc}")
            raise OnyxError(OnyxErrorCode.INTERNAL_ERROR, str(exc)) from exc

    # Session is now closed - streaming response won't hold DB connection
    async def audio_stream() -> AsyncIterator[bytes]:
        try:
            chunk_count = 0
            async for chunk in provider.synthesize_stream(
                text=text, voice=final_voice, speed=final_speed
            ):
                chunk_count += 1
                yield chunk
            logger.info(f"TTS streaming complete: {chunk_count} chunks sent")
        except NotImplementedError as exc:
            logger.error(f"TTS not implemented: {exc}")
            raise
        except Exception as exc:
            logger.error(f"Synthesis failed: {exc}")
            raise

    return StreamingResponse(
        audio_stream(),
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": "inline; filename=speech.mp3",
            # Allow streaming by not setting content-length
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
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
