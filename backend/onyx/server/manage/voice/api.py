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

logger = setup_logger()

admin_router = APIRouter(prefix="/admin/voice")
LOCAL_OPENAI_VOICE_PROVIDER_TYPE = "local_openai"

VOICE_PROVIDER_VALIDATION_FAILURE_MESSAGE = (
    "Connection test failed. Please verify your API key and settings."
)


def _validate_voice_api_base(provider_type: str, api_base: str | None) -> str | None:
    """Validate and normalize provider api_base / target URI."""
    if api_base is None:
        return None

    allow_private_network = provider_type.lower() in {
        "azure",
        LOCAL_OPENAI_VOICE_PROVIDER_TYPE,
    }
    try:
        return validate_outbound_http_url(
            api_base,
            allow_private_network=allow_private_network,
            block_link_local_only=provider_type.lower()
            == LOCAL_OPENAI_VOICE_PROVIDER_TYPE,
        )
    except (ValueError, SSRFException) as e:
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            f"Invalid target URI: {str(e)}",
        ) from e


def _validate_voice_custom_config(
    provider_type: str, custom_config: dict[str, object] | None
) -> dict[str, object] | None:
    """Validate provider-specific URLs stored in custom_config."""
    if custom_config is None:
        return None

    normalized = dict(custom_config)
    if provider_type.lower() == LOCAL_OPENAI_VOICE_PROVIDER_TYPE:
        for key in ("stt_api_base", "tts_api_base"):
            value = normalized.get(key)
            if value is None or value == "":
                normalized.pop(key, None)
                continue
            if not isinstance(value, str):
                raise OnyxError(
                    OnyxErrorCode.VALIDATION_ERROR,
                    f"{key} must be a URL string.",
                )
            normalized[key] = _validate_voice_api_base(provider_type, value)
    return normalized


def _voice_provider_requires_api_key(provider_type: str) -> bool:
    return provider_type.lower() != LOCAL_OPENAI_VOICE_PROVIDER_TYPE


def _local_voice_mode_has_base(provider: VoiceProvider, mode: str) -> bool:
    if provider.provider_type.lower() != LOCAL_OPENAI_VOICE_PROVIDER_TYPE:
        return True
    config = provider.custom_config or {}
    key = "stt_api_base" if mode == "stt" else "tts_api_base"
    mode_base = config.get(key)
    return bool(provider.api_base or (isinstance(mode_base, str) and mode_base))


def _validate_local_voice_mode_base(provider: VoiceProvider, mode: str) -> None:
    if _local_voice_mode_has_base(provider, mode):
        return
    raise OnyxError(
        OnyxErrorCode.VALIDATION_ERROR,
        f"Local {mode.upper()} API base URL is required.",
    )


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
        target_uri=provider.api_base,
        custom_config=provider.custom_config,
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

    custom_config = _validate_voice_custom_config(
        request.provider_type, request.custom_config
    )

    provider = upsert_voice_provider(
        db_session=db_session,
        provider_id=request.id,
        name=request.name,
        provider_type=request.provider_type,
        api_key=api_key,
        api_key_changed=api_key_changed,
        api_base=api_base,
        custom_config=custom_config,
        stt_model=request.stt_model,
        tts_model=request.tts_model,
        default_voice=request.default_voice,
        activate_stt=request.activate_stt,
        activate_tts=request.activate_tts,
    )

    if request.activate_stt:
        _validate_local_voice_mode_base(provider, "stt")
    if request.activate_tts:
        _validate_local_voice_mode_base(provider, "tts")

    # Validate credentials before committing - rollback on failure
    try:
        voice_provider = get_voice_provider(provider)
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
    provider_to_activate = fetch_voice_provider_by_id(db_session, provider_id)
    if provider_to_activate is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Voice provider not found.")
    _validate_local_voice_mode_base(provider_to_activate, "stt")
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
    provider_to_activate = fetch_voice_provider_by_id(db_session, provider_id)
    if provider_to_activate is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Voice provider not found.")
    _validate_local_voice_mode_base(provider_to_activate, "tts")
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

    if not api_key and _voice_provider_requires_api_key(request.provider_type):
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            "API key is required. Either provide api_key or set use_stored_key to true.",
        )

    # Use target_uri if provided, otherwise fall back to api_base
    api_base = _validate_voice_api_base(
        request.provider_type, request.target_uri or request.api_base
    )

    custom_config = _validate_voice_custom_config(
        request.provider_type, request.custom_config
    )

    # Create a temporary VoiceProvider for testing (not saved to DB)
    temp_provider = VoiceProvider(
        name="__test__",
        provider_type=request.provider_type,
        api_base=api_base,
        custom_config=custom_config or {},
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

    if not provider_db.api_key and _voice_provider_requires_api_key(
        provider_db.provider_type
    ):
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
