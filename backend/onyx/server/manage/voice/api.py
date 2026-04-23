from fastapi import APIRouter
from fastapi import Depends
from fastapi import Response
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import LLMProvider as LLMProviderModel
from onyx.db.models import User
from onyx.db.models import VoiceProvider
from onyx.db.voice import deactivate_stt_provider
from onyx.db.voice import deactivate_tts_provider
from onyx.db.voice import delete_voice_provider
from onyx.db.voice import fetch_voice_provider_by_id
from onyx.db.voice import fetch_voice_provider_by_type
from onyx.db.voice import fetch_voice_providers
from onyx.db.voice import set_default_stt_provider
from onyx.db.voice import set_default_tts_provider
from onyx.db.voice import upsert_voice_provider
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.voice.models import VoiceOption
from onyx.server.manage.voice.models import VoiceProviderTestRequest
from onyx.server.manage.voice.models import VoiceProviderUpdateSuccess
from onyx.server.manage.voice.models import VoiceProviderUpsertRequest
from onyx.server.manage.voice.models import VoiceProviderView
from onyx.utils.encryption import mask_string
from onyx.utils.logger import setup_logger
from onyx.utils.url import SSRFException
from onyx.utils.url import validate_outbound_http_url
from onyx.voice.factory import get_voice_provider

logger = setup_logger()

admin_router = APIRouter(prefix="/admin/voice")

VOICE_PROVIDER_VALIDATION_FAILURE_MESSAGE = (
    "Connection test failed. Please verify your API key and settings."
)


def _validate_voice_api_base(provider_type: str, api_base: str | None) -> str | None:
    """Validate and normalize provider api_base / target URI."""
    if api_base is None:
        return None

    allow_private_network = provider_type.lower() == "azure"
    try:
        return validate_outbound_http_url(
            api_base, allow_private_network=allow_private_network
        )
    except (ValueError, SSRFException) as e:
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            f"Invalid target URI: {str(e)}",
        ) from e


def _provider_to_view(provider: VoiceProvider) -> VoiceProviderView:
    """Convert a VoiceProvider model to a VoiceProviderView."""
    raw_key = provider.api_key.get_value(apply_mask=False) if provider.api_key else None
    return VoiceProviderView(
        id=provider.id,
        name=provider.name,
        provider_type=provider.provider_type,
        is_default_stt=provider.is_default_stt,
        is_default_tts=provider.is_default_tts,
        stt_model=provider.stt_model,
        tts_model=provider.tts_model,
        default_voice=provider.default_voice,
        api_key=mask_string(raw_key) if raw_key else None,
        has_api_key=bool(provider.api_key),
        target_uri=provider.api_base,  # api_base stores the target URI for Azure
    )


@admin_router.get("/providers")
def list_voice_providers(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[VoiceProviderView]:
    """List all configured voice providers."""
    providers = fetch_voice_providers(db_session)
    return [_provider_to_view(provider) for provider in providers]


@admin_router.post("/providers")
async def upsert_voice_provider_endpoint(
    request: VoiceProviderUpsertRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> VoiceProviderView:
    """Create or update a voice provider."""
    api_key = request.api_key
    api_key_changed = request.api_key_changed

    # If llm_provider_id is specified, copy the API key from that LLM provider
    if request.llm_provider_id is not None:
        llm_provider = db_session.get(LLMProviderModel, request.llm_provider_id)
        if llm_provider is None:
            raise OnyxError(
                OnyxErrorCode.NOT_FOUND,
                f"LLM provider with id {request.llm_provider_id} not found.",
            )
        if llm_provider.api_key is None:
            raise OnyxError(
                OnyxErrorCode.VALIDATION_ERROR,
                "Selected LLM provider has no API key configured.",
            )
        api_key = llm_provider.api_key.get_value(apply_mask=False)
        api_key_changed = True

    # Use target_uri if provided, otherwise fall back to api_base
    api_base = _validate_voice_api_base(
        request.provider_type, request.target_uri or request.api_base
    )

    provider = upsert_voice_provider(
        db_session=db_session,
        provider_id=request.id,
        name=request.name,
        provider_type=request.provider_type,
        api_key=api_key,
        api_key_changed=api_key_changed,
        api_base=api_base,
        custom_config=request.custom_config,
        stt_model=request.stt_model,
        tts_model=request.tts_model,
        default_voice=request.default_voice,
        activate_stt=request.activate_stt,
        activate_tts=request.activate_tts,
    )

    # Validate credentials before committing - rollback on failure
    try:
        voice_provider = get_voice_provider(provider)
        await voice_provider.validate_credentials()
    except OnyxError:
        db_session.rollback()
        raise
    except Exception as e:
        db_session.rollback()
        logger.error(f"Voice provider credential validation failed on save: {e}")
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            VOICE_PROVIDER_VALIDATION_FAILURE_MESSAGE,
        ) from e

    db_session.commit()

    return _provider_to_view(provider)


@admin_router.delete(
    "/providers/{provider_id}", status_code=204, response_class=Response
)
def delete_voice_provider_endpoint(
    provider_id: int,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> Response:
    """Delete a voice provider."""
    delete_voice_provider(db_session, provider_id)
    db_session.commit()
    return Response(status_code=204)


@admin_router.post("/providers/{provider_id}/activate-stt")
def activate_stt_provider_endpoint(
    provider_id: int,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> VoiceProviderView:
    """Set a voice provider as the default STT provider."""
    provider = set_default_stt_provider(db_session=db_session, provider_id=provider_id)
    db_session.commit()
    return _provider_to_view(provider)


@admin_router.post("/providers/{provider_id}/deactivate-stt")
def deactivate_stt_provider_endpoint(
    provider_id: int,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> VoiceProviderUpdateSuccess:
    """Remove the default STT status from a voice provider."""
    deactivate_stt_provider(db_session=db_session, provider_id=provider_id)
    db_session.commit()
    return VoiceProviderUpdateSuccess()


@admin_router.post("/providers/{provider_id}/activate-tts")
def activate_tts_provider_endpoint(
    provider_id: int,
    tts_model: str | None = None,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> VoiceProviderView:
    """Set a voice provider as the default TTS provider."""
    provider = set_default_tts_provider(
        db_session=db_session, provider_id=provider_id, tts_model=tts_model
    )
    db_session.commit()
    return _provider_to_view(provider)


@admin_router.post("/providers/{provider_id}/deactivate-tts")
def deactivate_tts_provider_endpoint(
    provider_id: int,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> VoiceProviderUpdateSuccess:
    """Remove the default TTS status from a voice provider."""
    deactivate_tts_provider(db_session=db_session, provider_id=provider_id)
    db_session.commit()
    return VoiceProviderUpdateSuccess()


@admin_router.post("/providers/test")
async def test_voice_provider(
    request: VoiceProviderTestRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> VoiceProviderUpdateSuccess:
    """Test a voice provider connection by making a real API call."""
    api_key = request.api_key

    if request.use_stored_key:
        existing_provider = fetch_voice_provider_by_type(
            db_session, request.provider_type
        )
        if existing_provider is None or not existing_provider.api_key:
            raise OnyxError(
                OnyxErrorCode.VALIDATION_ERROR,
                "No stored API key found for this provider type.",
            )
        api_key = existing_provider.api_key.get_value(apply_mask=False)

    if not api_key:
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            "API key is required. Either provide api_key or set use_stored_key to true.",
        )

    # Use target_uri if provided, otherwise fall back to api_base
    api_base = _validate_voice_api_base(
        request.provider_type, request.target_uri or request.api_base
    )

    # Create a temporary VoiceProvider for testing (not saved to DB)
    temp_provider = VoiceProvider(
        name="__test__",
        provider_type=request.provider_type,
        api_base=api_base,
        custom_config=request.custom_config or {},
    )
    temp_provider.api_key = api_key  # ty: ignore[invalid-assignment]

    try:
        provider = get_voice_provider(temp_provider)
    except ValueError as exc:
        raise OnyxError(OnyxErrorCode.VALIDATION_ERROR, str(exc)) from exc

    # Validate credentials with a real API call
    try:
        await provider.validate_credentials()
    except OnyxError:
        raise
    except Exception as e:
        logger.error(f"Voice provider connection test failed: {e}")
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            VOICE_PROVIDER_VALIDATION_FAILURE_MESSAGE,
        ) from e

    logger.info(f"Voice provider test succeeded for {request.provider_type}.")
    return VoiceProviderUpdateSuccess()


@admin_router.get("/providers/{provider_id}/voices")
def get_provider_voices(
    provider_id: int,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[VoiceOption]:
    """Get available voices for a provider."""
    provider_db = fetch_voice_provider_by_id(db_session, provider_id)
    if provider_db is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Voice provider not found.")

    if not provider_db.api_key:
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR, "Provider has no API key configured."
        )

    try:
        provider = get_voice_provider(provider_db)
    except ValueError as exc:
        raise OnyxError(OnyxErrorCode.VALIDATION_ERROR, str(exc)) from exc

    return [VoiceOption(**voice) for voice in provider.get_available_voices()]


@admin_router.get("/voices")
def get_voices_by_type(
    provider_type: str,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
) -> list[VoiceOption]:
    """Get available voices for a provider type.

    For providers like ElevenLabs and OpenAI, this fetches voices
    without requiring an existing provider configuration.
    """
    # Create a temporary VoiceProvider to get static voice list
    temp_provider = VoiceProvider(
        name="__temp__",
        provider_type=provider_type,
    )

    try:
        provider = get_voice_provider(temp_provider)
    except ValueError as exc:
        raise OnyxError(OnyxErrorCode.VALIDATION_ERROR, str(exc)) from exc

    return [VoiceOption(**voice) for voice in provider.get_available_voices()]
