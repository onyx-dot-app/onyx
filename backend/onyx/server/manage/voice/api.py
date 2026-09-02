from typing import Any, cast

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import LLMProvider as LLMProviderModel
from onyx.db.models import User, VoiceProvider
from onyx.db.voice import (
    deactivate_stt_provider,
    deactivate_tts_provider,
    delete_voice_provider,
    fetch_voice_provider_by_id,
    fetch_voice_provider_by_type,
    fetch_voice_providers,
    set_default_stt_provider,
    set_default_tts_provider,
    upsert_voice_provider,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.voice.models import (
    VoiceOption,
    VoiceProviderTestRequest,
    VoiceProviderUpdateSuccess,
    VoiceProviderUpsertRequest,
    VoiceProviderView,
)
from onyx.utils.encryption import mask_string
from onyx.utils.logger import setup_logger
from onyx.utils.url import SSRFException, validate_outbound_http_url
from onyx.voice.factory import get_voice_provider
from onyx.voice.interface import VoiceProviderInterface

logger = setup_logger()

admin_router = APIRouter(prefix="/admin/voice")

VOICE_PROVIDER_VALIDATION_FAILURE_MESSAGE = (
    "Connection test failed. Please verify your credentials and settings."
)
STORED_API_SECRET_PLACEHOLDER = "********"
_CUSTOM_CONFIG_CREDENTIAL_KEYS = {"api_key", "api_secret"}


def _contains_custom_config_credential_key(value: object) -> bool:
    if isinstance(value, dict):
        for key, nested_value in value.items():
            if isinstance(key, str) and key.lower() in _CUSTOM_CONFIG_CREDENTIAL_KEYS:
                return True
            if _contains_custom_config_credential_key(nested_value):
                return True
    if isinstance(value, list):
        return any(_contains_custom_config_credential_key(item) for item in value)
    return False


def _reject_custom_config_credentials(
    custom_config: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if custom_config is not None and _contains_custom_config_credential_key(
        custom_config
    ):
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            "Voice provider custom_config cannot contain API credentials.",
        )
    return custom_config


def _sanitize_custom_config_for_response(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _sanitize_custom_config_for_response(nested_value)
            for key, nested_value in value.items()
            if not (
                isinstance(key, str) and key.lower() in _CUSTOM_CONFIG_CREDENTIAL_KEYS
            )
        }
    if isinstance(value, list):
        return [_sanitize_custom_config_for_response(item) for item in value]
    return value


def _custom_config_to_view(
    custom_config: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if custom_config is None:
        return None
    return cast(dict[str, Any], _sanitize_custom_config_for_response(custom_config))


def _validate_tts_activation_supported(
    voice_provider: VoiceProviderInterface,
) -> None:
    if not voice_provider.get_available_tts_models():
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            "Voice provider does not support text-to-speech.",
        )


def _validate_voice_api_base(provider_type: str, api_base: str | None) -> str | None:
    """Validate and normalize provider api_base / target URI."""
    if api_base is None:
        return None

    if provider_type.lower() == "zoom":
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            "Zoom voice providers do not support a target URI.",
        )

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
        api_secret=STORED_API_SECRET_PLACEHOLDER if provider.api_secret else None,
        target_uri=provider.api_base,  # api_base stores the target URI for Azure
        custom_config=_custom_config_to_view(provider.custom_config),
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
    api_secret = request.api_secret
    api_secret_changed = request.api_secret_changed

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
    custom_config = _reject_custom_config_credentials(request.custom_config)

    provider = upsert_voice_provider(
        db_session=db_session,
        provider_id=request.id,
        name=request.name,
        provider_type=request.provider_type,
        api_key=api_key,
        api_key_changed=api_key_changed,
        api_secret=api_secret,
        api_secret_changed=api_secret_changed,
        api_base=api_base,
        custom_config=custom_config,
        stt_model=request.stt_model,
        tts_model=request.tts_model,
        default_voice=request.default_voice,
        activate_stt=request.activate_stt,
        activate_tts=request.activate_tts,
    )

    # Validate credentials before committing - rollback on failure
    try:
        voice_provider = get_voice_provider(provider)
        if request.activate_tts:
            _validate_tts_activation_supported(voice_provider)
        await voice_provider.validate_credentials()
    except OnyxError:
        db_session.rollback()
        raise
    except ValueError as e:
        # Bad provider config (e.g. invalid stt_languages) — surface the real reason.
        db_session.rollback()
        raise OnyxError(OnyxErrorCode.VALIDATION_ERROR, str(e)) from e
    except Exception as e:
        db_session.rollback()
        logger.error("Voice provider credential validation failed on save: %s", e)
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
    provider_db = fetch_voice_provider_by_id(db_session, provider_id)
    if provider_db is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"No voice provider with id {provider_id} exists.",
        )

    try:
        voice_provider = get_voice_provider(provider_db)
        _validate_tts_activation_supported(voice_provider)
    except ValueError as exc:
        raise OnyxError(OnyxErrorCode.VALIDATION_ERROR, str(exc)) from exc

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
    api_secret = request.api_secret
    existing_provider: VoiceProvider | None = None

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

    if request.use_stored_secret:
        if existing_provider is None:
            existing_provider = fetch_voice_provider_by_type(
                db_session, request.provider_type
            )
        if existing_provider is None or not existing_provider.api_secret:
            raise OnyxError(
                OnyxErrorCode.VALIDATION_ERROR,
                "No stored API secret found for this provider type.",
            )
        api_secret = existing_provider.api_secret.get_value(apply_mask=False)

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
    temp_provider.api_secret = api_secret  # ty: ignore[invalid-assignment]

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
        logger.error("Voice provider connection test failed: %s", e)
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            VOICE_PROVIDER_VALIDATION_FAILURE_MESSAGE,
        ) from e

    logger.info("Voice provider test succeeded for %s.", request.provider_type)
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
