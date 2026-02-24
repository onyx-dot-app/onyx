from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Response
from sqlalchemy.orm import Session

from onyx.auth.users import current_admin_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import User
from onyx.db.voice import deactivate_stt_provider
from onyx.db.voice import deactivate_tts_provider
from onyx.db.voice import delete_voice_provider
from onyx.db.voice import fetch_voice_provider_by_id
from onyx.db.voice import fetch_voice_provider_by_type
from onyx.db.voice import fetch_voice_providers
from onyx.db.voice import set_default_stt_provider
from onyx.db.voice import set_default_tts_provider
from onyx.db.voice import upsert_voice_provider
from onyx.server.manage.voice.models import VoiceProviderTestRequest
from onyx.server.manage.voice.models import VoiceProviderUpsertRequest
from onyx.server.manage.voice.models import VoiceProviderView
from onyx.utils.logger import setup_logger
from onyx.voice.factory import get_voice_provider

logger = setup_logger()

admin_router = APIRouter(prefix="/admin/voice")


def _provider_to_view(provider) -> VoiceProviderView:
    """Convert a VoiceProvider model to a VoiceProviderView."""
    return VoiceProviderView(
        id=provider.id,
        name=provider.name,
        provider_type=provider.provider_type,
        is_default_stt=provider.is_default_stt,
        is_default_tts=provider.is_default_tts,
        stt_model=provider.stt_model,
        tts_model=provider.tts_model,
        default_voice=provider.default_voice,
        has_api_key=bool(provider.api_key),
    )


@admin_router.get("/providers")
def list_voice_providers(
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[VoiceProviderView]:
    """List all configured voice providers."""
    providers = fetch_voice_providers(db_session)
    return [_provider_to_view(provider) for provider in providers]


@admin_router.post("/providers")
def upsert_voice_provider_endpoint(
    request: VoiceProviderUpsertRequest,
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> VoiceProviderView:
    """Create or update a voice provider."""
    provider = upsert_voice_provider(
        db_session=db_session,
        provider_id=request.id,
        name=request.name,
        provider_type=request.provider_type,
        api_key=request.api_key,
        api_key_changed=request.api_key_changed,
        api_base=request.api_base,
        custom_config=request.custom_config,
        stt_model=request.stt_model,
        tts_model=request.tts_model,
        default_voice=request.default_voice,
        activate_stt=request.activate_stt,
        activate_tts=request.activate_tts,
    )

    db_session.commit()

    return _provider_to_view(provider)


@admin_router.delete(
    "/providers/{provider_id}", status_code=204, response_class=Response
)
def delete_voice_provider_endpoint(
    provider_id: int,
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> Response:
    """Delete a voice provider."""
    delete_voice_provider(db_session, provider_id)
    return Response(status_code=204)


@admin_router.post("/providers/{provider_id}/activate-stt")
def activate_stt_provider_endpoint(
    provider_id: int,
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> VoiceProviderView:
    """Set a voice provider as the default STT provider."""
    provider = set_default_stt_provider(db_session=db_session, provider_id=provider_id)
    db_session.commit()
    return _provider_to_view(provider)


@admin_router.post("/providers/{provider_id}/deactivate-stt")
def deactivate_stt_provider_endpoint(
    provider_id: int,
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> dict[str, str]:
    """Remove the default STT status from a voice provider."""
    deactivate_stt_provider(db_session=db_session, provider_id=provider_id)
    db_session.commit()
    return {"status": "ok"}


@admin_router.post("/providers/{provider_id}/activate-tts")
def activate_tts_provider_endpoint(
    provider_id: int,
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> VoiceProviderView:
    """Set a voice provider as the default TTS provider."""
    provider = set_default_tts_provider(db_session=db_session, provider_id=provider_id)
    db_session.commit()
    return _provider_to_view(provider)


@admin_router.post("/providers/{provider_id}/deactivate-tts")
def deactivate_tts_provider_endpoint(
    provider_id: int,
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> dict[str, str]:
    """Remove the default TTS status from a voice provider."""
    deactivate_tts_provider(db_session=db_session, provider_id=provider_id)
    db_session.commit()
    return {"status": "ok"}


@admin_router.post("/providers/test")
def test_voice_provider(
    request: VoiceProviderTestRequest,
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> dict[str, str]:
    """Test a voice provider connection."""
    api_key = request.api_key

    if request.use_stored_key:
        existing_provider = fetch_voice_provider_by_type(
            db_session, request.provider_type
        )
        if existing_provider is None or not existing_provider.api_key:
            raise HTTPException(
                status_code=400,
                detail="No stored API key found for this provider type.",
            )
        api_key = existing_provider.api_key.get_value(apply_mask=False)

    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="API key is required. Either provide api_key or set use_stored_key to true.",
        )

    try:
        provider = get_voice_provider(
            provider_type=request.provider_type,
            api_key=api_key,
            api_base=request.api_base,
            custom_config=request.custom_config or {},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if provider is None:
        raise HTTPException(
            status_code=400, detail="Unable to build provider configuration."
        )

    # Test the provider by getting available voices (lightweight check)
    try:
        voices = provider.get_available_voices()
        if not voices:
            raise HTTPException(
                status_code=400,
                detail="Provider returned no available voices.",
            )
    except NotImplementedError:
        # Provider not fully implemented yet (Azure, ElevenLabs placeholders)
        pass
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Connection test failed: {str(e)}",
        ) from e

    logger.info(f"Voice provider test succeeded for {request.provider_type}.")
    return {"status": "ok"}


@admin_router.get("/providers/{provider_id}/voices")
def get_provider_voices(
    provider_id: int,
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[dict[str, str]]:
    """Get available voices for a provider."""
    provider_db = fetch_voice_provider_by_id(db_session, provider_id)
    if provider_db is None:
        raise HTTPException(status_code=404, detail="Voice provider not found.")

    if not provider_db.api_key:
        raise HTTPException(
            status_code=400, detail="Provider has no API key configured."
        )

    try:
        provider = get_voice_provider(
            provider_type=provider_db.provider_type,
            api_key=provider_db.api_key.get_value(apply_mask=False),
            api_base=provider_db.api_base,
            custom_config=provider_db.custom_config or {},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return provider.get_available_voices()
