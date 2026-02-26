from fastapi import APIRouter
from fastapi import Depends
from fastapi import File
from fastapi import HTTPException
from fastapi import UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import User
from onyx.db.voice import fetch_default_stt_provider
from onyx.db.voice import fetch_default_tts_provider
from onyx.db.voice import update_user_voice_settings
from onyx.server.manage.models import VoiceSettingsUpdateRequest
from onyx.server.manage.voice.models import SynthesizeRequest
from onyx.utils.logger import setup_logger
from onyx.voice.factory import get_voice_provider

logger = setup_logger()

router = APIRouter(prefix="/voice")

# Max audio file size: 25MB (Whisper limit)
MAX_AUDIO_SIZE = 25 * 1024 * 1024


@router.post("/transcribe")
async def transcribe_audio(
    audio: UploadFile = File(...),
    _: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> dict[str, str]:
    """Transcribe audio to text using the default STT provider."""
    provider_db = fetch_default_stt_provider(db_session)
    if provider_db is None:
        raise HTTPException(
            status_code=400,
            detail="No speech-to-text provider configured. Please contact your administrator.",
        )

    if not provider_db.api_key:
        raise HTTPException(
            status_code=400,
            detail="Voice provider API key not configured.",
        )

    audio_data = await audio.read()
    if len(audio_data) > MAX_AUDIO_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"Audio file too large. Maximum size is {MAX_AUDIO_SIZE // (1024 * 1024)}MB.",
        )

    # Extract format from filename
    filename = audio.filename or "audio.webm"
    audio_format = filename.rsplit(".", 1)[-1] if "." in filename else "webm"

    try:
        provider = get_voice_provider(
            provider_type=provider_db.provider_type,
            api_key=provider_db.api_key.get_value(apply_mask=False),
            api_base=provider_db.api_base,
            custom_config=provider_db.custom_config or {},
            stt_model=provider_db.stt_model,
            tts_model=provider_db.tts_model,
            default_voice=provider_db.default_voice,
        )
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    try:
        text = await provider.transcribe(audio_data, audio_format)
        return {"text": text}
    except NotImplementedError as exc:
        raise HTTPException(
            status_code=501,
            detail=f"Speech-to-text not implemented for {provider_db.provider_type}.",
        ) from exc
    except Exception as exc:
        logger.error(f"Transcription failed: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"Transcription failed: {str(exc)}",
        ) from exc


@router.post("/synthesize")
async def synthesize_speech(
    request: SynthesizeRequest,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> StreamingResponse:
    """Synthesize text to speech using the default TTS provider."""
    provider_db = fetch_default_tts_provider(db_session)
    if provider_db is None:
        raise HTTPException(
            status_code=400,
            detail="No text-to-speech provider configured. Please contact your administrator.",
        )

    if not provider_db.api_key:
        raise HTTPException(
            status_code=400,
            detail="Voice provider API key not configured.",
        )

    # Use request voice, or user's preferred voice, or provider default
    voice = request.voice or user.preferred_voice or provider_db.default_voice
    speed = request.speed or user.voice_playback_speed or 1.0

    try:
        provider = get_voice_provider(
            provider_type=provider_db.provider_type,
            api_key=provider_db.api_key.get_value(apply_mask=False),
            api_base=provider_db.api_base,
            custom_config=provider_db.custom_config or {},
            stt_model=provider_db.stt_model,
            tts_model=provider_db.tts_model,
            default_voice=provider_db.default_voice,
        )
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    async def audio_stream():
        try:
            async for chunk in provider.synthesize_stream(
                text=request.text, voice=voice, speed=speed
            ):
                yield chunk
        except NotImplementedError as exc:
            logger.error(f"TTS not implemented: {exc}")
            raise
        except Exception as exc:
            logger.error(f"Synthesis failed: {exc}")
            raise

    return StreamingResponse(
        audio_stream(),
        media_type="audio/mpeg",
        headers={"Content-Disposition": "inline; filename=speech.mp3"},
    )


@router.patch("/settings")
def update_voice_settings(
    request: VoiceSettingsUpdateRequest,
    user: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> dict[str, str]:
    """Update user's voice settings."""
    update_user_voice_settings(
        db_session=db_session,
        user_id=user.id,
        auto_send=request.auto_send,
        auto_playback=request.auto_playback,
        playback_speed=request.playback_speed,
        preferred_voice=request.preferred_voice,
    )
    return {"status": "ok"}
