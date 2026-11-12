from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from onyx.db.enums import LLMModelFlowType
from onyx.db.llm import (
    fetch_llm_provider_by_zoom_voice_provider_id,
    remove_llm_provider,
)
from onyx.db.models import (
    LLMModelFlow,
    LLMProvider,
    ModelConfiguration,
    User,
    VoiceProvider,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.voice.interface import normalize_provider_type

MIN_VOICE_PLAYBACK_SPEED = 0.5
MAX_VOICE_PLAYBACK_SPEED = 2.0


def fetch_voice_providers(db_session: Session) -> list[VoiceProvider]:
    """Fetch all voice providers."""
    return list(
        db_session.scalars(select(VoiceProvider).order_by(VoiceProvider.name)).all()
    )


def fetch_voice_provider_by_id(
    db_session: Session, provider_id: int, *, for_update: bool = False
) -> VoiceProvider | None:
    """Fetch a voice provider by ID.

    `for_update` locks the row until the transaction ends, so a concurrent
    upsert cannot change the row between a capability check and an update.
    """
    stmt = select(VoiceProvider).where(VoiceProvider.id == provider_id)
    if for_update:
        stmt = stmt.with_for_update()
    return db_session.scalar(stmt)


def fetch_default_stt_provider(db_session: Session) -> VoiceProvider | None:
    """Fetch the default STT provider."""
    return db_session.scalar(
        select(VoiceProvider).where(VoiceProvider.is_default_stt.is_(True))
    )


def fetch_default_tts_provider(db_session: Session) -> VoiceProvider | None:
    """Fetch the default TTS provider."""
    return db_session.scalar(
        select(VoiceProvider).where(VoiceProvider.is_default_tts.is_(True))
    )


def fetch_voice_provider_by_type(
    db_session: Session, provider_type: str
) -> VoiceProvider | None:
    """Fetch one provider by normalized type, rejecting ambiguous matches.

    Rows are matched in Python with normalize_provider_type so legacy values
    follow the same rule as requests. The table holds a handful of rows.
    """
    wanted = normalize_provider_type(provider_type)
    providers = [
        provider
        for provider in db_session.scalars(select(VoiceProvider)).all()
        if normalize_provider_type(provider.provider_type) == wanted
    ]
    if len(providers) > 1:
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            "Multiple voice providers match this type. Provide an API key explicitly.",
        )
    return providers[0] if providers else None


def upsert_voice_provider(
    *,
    db_session: Session,
    provider_id: int | None,
    name: str,
    provider_type: str,
    api_key: str | None,
    api_key_changed: bool,
    api_secret: str | None = None,
    api_secret_changed: bool = False,
    api_base: str | None = None,
    custom_config: dict[str, Any] | None = None,
    stt_model: str | None = None,
    tts_model: str | None = None,
    default_voice: str | None = None,
    activate_stt: bool = False,
    activate_tts: bool = False,
    link_decision_provider: bool = False,
) -> VoiceProvider:
    """Create or update a voice provider."""
    provider: VoiceProvider | None = None

    if provider_id is not None:
        provider = fetch_voice_provider_by_id(db_session, provider_id, for_update=True)
        if provider is None:
            raise OnyxError(
                OnyxErrorCode.NOT_FOUND,
                f"No voice provider with id {provider_id} exists.",
            )
        if (
            normalize_provider_type(provider.provider_type) == "zoom"
            and normalize_provider_type(provider_type) != "zoom"
        ):
            raise OnyxError(
                OnyxErrorCode.VALIDATION_ERROR,
                "A shared Zoom connection cannot change provider type.",
            )
    else:
        provider = VoiceProvider()
        db_session.add(provider)

    # Apply updates
    provider.name = name
    provider.provider_type = provider_type
    provider.api_base = api_base
    # None means "leave unchanged" (pass {} to clear) so partial writers can't
    # wipe keys like speech_region.
    if custom_config is not None:
        provider.custom_config = custom_config
    provider.stt_model = stt_model
    provider.tts_model = tts_model
    provider.default_voice = default_voice

    # Only update API key if explicitly changed or if provider has no key
    if api_key_changed or provider.api_key is None:
        provider.api_key = api_key  # ty: ignore[invalid-assignment]

    if api_secret_changed or provider.api_secret is None:
        provider.api_secret = api_secret  # ty: ignore[invalid-assignment]

    db_session.flush()

    if normalize_provider_type(provider_type) == "zoom" and (
        link_decision_provider
        or fetch_llm_provider_by_zoom_voice_provider_id(db_session, provider.id)
    ):
        ensure_zoom_decision_provider(db_session, provider)

    if activate_stt:
        set_default_stt_provider(db_session=db_session, provider_id=provider.id)
    if activate_tts:
        set_default_tts_provider(db_session=db_session, provider_id=provider.id)

    db_session.refresh(provider)
    return provider


def ensure_zoom_decision_provider(
    db_session: Session, voice: VoiceProvider
) -> LLMProvider:
    provider = fetch_llm_provider_by_zoom_voice_provider_id(db_session, voice.id)
    if provider is None:
        provider = LLMProvider(
            name=voice.name,
            provider="zoom_ai",
            zoom_voice_provider_id=voice.id,
            is_public=True,
            is_auto_mode=False,
        )
        db_session.add(provider)
        db_session.flush()
    provider.name = voice.name
    for name, label in (
        ("zoom-decisions", "Zoom Decisions"),
        ("zoom-decisions-pro", "Zoom Decisions Pro"),
    ):
        model = db_session.scalar(
            select(ModelConfiguration).where(
                ModelConfiguration.llm_provider_id == provider.id,
                ModelConfiguration.name == name,
            )
        )
        if model is None:
            model = ModelConfiguration(
                llm_provider_id=provider.id,
                name=name,
                display_name=label,
                is_visible=False,
            )
            db_session.add(model)
            db_session.flush()
        flow = db_session.scalar(
            select(LLMModelFlow).where(
                LLMModelFlow.model_configuration_id == model.id,
                LLMModelFlow.llm_model_flow_type == LLMModelFlowType.DECISION,
            )
        )
        if flow is None:
            db_session.add(
                LLMModelFlow(
                    model_configuration_id=model.id,
                    llm_model_flow_type=LLMModelFlowType.DECISION,
                    is_default=False,
                )
            )
    db_session.flush()
    return provider


def delete_voice_provider(db_session: Session, provider_id: int) -> None:
    """Delete a voice provider by ID."""
    provider = fetch_voice_provider_by_id(db_session, provider_id, for_update=True)
    if provider:
        linked = db_session.scalars(
            select(LLMProvider).where(LLMProvider.zoom_voice_provider_id == provider_id)
        ).all()
        for decision in linked:
            selected = db_session.scalar(
                select(LLMModelFlow.id)
                .join(ModelConfiguration)
                .where(
                    ModelConfiguration.llm_provider_id == decision.id,
                    LLMModelFlow.is_default.is_(True),
                )
                .limit(1)
            )
            if selected is not None:
                raise OnyxError(
                    OnyxErrorCode.RESOURCE_IN_USE,
                    "Clear the selected decision model before removing this Zoom connection.",
                )
            remove_llm_provider(db_session, decision.id, commit=False)
        db_session.delete(provider)
        db_session.flush()


def set_default_stt_provider(*, db_session: Session, provider_id: int) -> VoiceProvider:
    """Set a voice provider as the default STT provider."""
    provider = fetch_voice_provider_by_id(db_session, provider_id)
    if provider is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"No voice provider with id {provider_id} exists.",
        )

    # Deactivate all other STT providers
    db_session.execute(
        update(VoiceProvider)
        .where(
            VoiceProvider.is_default_stt.is_(True),
            VoiceProvider.id != provider_id,
        )
        .values(is_default_stt=False)
    )

    # Activate this provider
    provider.is_default_stt = True

    db_session.flush()
    db_session.refresh(provider)
    return provider


def set_default_tts_provider(
    *, db_session: Session, provider_id: int, tts_model: str | None = None
) -> VoiceProvider:
    """Set a voice provider as the default TTS provider."""
    provider = fetch_voice_provider_by_id(db_session, provider_id)
    if provider is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"No voice provider with id {provider_id} exists.",
        )

    # Deactivate all other TTS providers
    db_session.execute(
        update(VoiceProvider)
        .where(
            VoiceProvider.is_default_tts.is_(True),
            VoiceProvider.id != provider_id,
        )
        .values(is_default_tts=False)
    )

    # Activate this provider
    provider.is_default_tts = True

    # Update the TTS model if specified
    if tts_model is not None:
        provider.tts_model = tts_model

    db_session.flush()
    db_session.refresh(provider)
    return provider


def deactivate_stt_provider(*, db_session: Session, provider_id: int) -> VoiceProvider:
    """Remove the default STT status from a voice provider."""
    provider = fetch_voice_provider_by_id(db_session, provider_id)
    if provider is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"No voice provider with id {provider_id} exists.",
        )

    provider.is_default_stt = False

    db_session.flush()
    db_session.refresh(provider)
    return provider


def deactivate_tts_provider(*, db_session: Session, provider_id: int) -> VoiceProvider:
    """Remove the default TTS status from a voice provider."""
    provider = fetch_voice_provider_by_id(db_session, provider_id)
    if provider is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"No voice provider with id {provider_id} exists.",
        )

    provider.is_default_tts = False

    db_session.flush()
    db_session.refresh(provider)
    return provider


# User voice preferences


def update_user_voice_settings(
    db_session: Session,
    user_id: UUID,
    auto_send: bool | None = None,
    auto_playback: bool | None = None,
    playback_speed: float | None = None,
) -> None:
    """Update user's voice settings.

    For all fields, None means "don't update this field".
    """
    values: dict[str, bool | float] = {}

    if auto_send is not None:
        values["voice_auto_send"] = auto_send
    if auto_playback is not None:
        values["voice_auto_playback"] = auto_playback
    if playback_speed is not None:
        values["voice_playback_speed"] = max(
            MIN_VOICE_PLAYBACK_SPEED, min(MAX_VOICE_PLAYBACK_SPEED, playback_speed)
        )

    if values:
        db_session.execute(
            update(User)
            .where(User.id == user_id)  # ty: ignore[invalid-argument-type]
            .values(**values)
        )
        db_session.flush()
