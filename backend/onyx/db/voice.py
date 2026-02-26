from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.orm import Session

from onyx.db.models import User
from onyx.db.models import VoiceProvider


def fetch_voice_providers(db_session: Session) -> list[VoiceProvider]:
    """Fetch all voice providers."""
    return list(
        db_session.scalars(select(VoiceProvider).order_by(VoiceProvider.name)).all()
    )


def fetch_voice_provider_by_id(
    db_session: Session, provider_id: int
) -> VoiceProvider | None:
    """Fetch a voice provider by ID."""
    return db_session.scalar(
        select(VoiceProvider).where(VoiceProvider.id == provider_id)
    )


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
    """Fetch a voice provider by type."""
    return db_session.scalar(
        select(VoiceProvider).where(VoiceProvider.provider_type == provider_type)
    )


def upsert_voice_provider(
    *,
    db_session: Session,
    provider_id: int | None,
    name: str,
    provider_type: str,
    api_key: str | None,
    api_key_changed: bool,
    api_base: str | None = None,
    custom_config: dict[str, Any] | None = None,
    stt_model: str | None = None,
    tts_model: str | None = None,
    default_voice: str | None = None,
    activate_stt: bool = False,
    activate_tts: bool = False,
) -> VoiceProvider:
    """Create or update a voice provider."""
    provider: VoiceProvider | None = None

    if provider_id is not None:
        provider = fetch_voice_provider_by_id(db_session, provider_id)
        if provider is None:
            raise ValueError(f"No voice provider with id {provider_id} exists.")
    else:
        provider = VoiceProvider()
        db_session.add(provider)

    # Apply updates
    provider.name = name
    provider.provider_type = provider_type
    provider.api_base = api_base
    provider.custom_config = custom_config
    provider.stt_model = stt_model
    provider.tts_model = tts_model
    provider.default_voice = default_voice

    # Only update API key if explicitly changed or if provider has no key
    if api_key_changed or provider.api_key is None:
        provider.api_key = api_key  # type: ignore[assignment]

    db_session.flush()

    if activate_stt:
        set_default_stt_provider(db_session=db_session, provider_id=provider.id)
    if activate_tts:
        set_default_tts_provider(db_session=db_session, provider_id=provider.id)

    db_session.refresh(provider)
    return provider


def delete_voice_provider(db_session: Session, provider_id: int) -> None:
    """Delete a voice provider by ID."""
    provider = fetch_voice_provider_by_id(db_session, provider_id)
    if provider:
        db_session.delete(provider)
        db_session.commit()


def set_default_stt_provider(*, db_session: Session, provider_id: int) -> VoiceProvider:
    """Set a voice provider as the default STT provider."""
    provider = fetch_voice_provider_by_id(db_session, provider_id)
    if provider is None:
        raise ValueError(f"No voice provider with id {provider_id} exists.")

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


def set_default_tts_provider(*, db_session: Session, provider_id: int) -> VoiceProvider:
    """Set a voice provider as the default TTS provider."""
    provider = fetch_voice_provider_by_id(db_session, provider_id)
    if provider is None:
        raise ValueError(f"No voice provider with id {provider_id} exists.")

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

    db_session.flush()
    db_session.refresh(provider)
    return provider


def deactivate_stt_provider(*, db_session: Session, provider_id: int) -> VoiceProvider:
    """Remove the default STT status from a voice provider."""
    provider = fetch_voice_provider_by_id(db_session, provider_id)
    if provider is None:
        raise ValueError(f"No voice provider with id {provider_id} exists.")

    provider.is_default_stt = False

    db_session.flush()
    db_session.refresh(provider)
    return provider


def deactivate_tts_provider(*, db_session: Session, provider_id: int) -> VoiceProvider:
    """Remove the default TTS status from a voice provider."""
    provider = fetch_voice_provider_by_id(db_session, provider_id)
    if provider is None:
        raise ValueError(f"No voice provider with id {provider_id} exists.")

    provider.is_default_tts = False

    db_session.flush()
    db_session.refresh(provider)
    return provider


# User voice preferences


def update_user_voice_auto_send(
    db_session: Session, user_id: UUID, auto_send: bool
) -> None:
    """Update user's voice auto-send setting."""
    db_session.execute(
        update(User).where(User.id == user_id).values(voice_auto_send=auto_send)
    )
    db_session.commit()


def update_user_voice_auto_playback(
    db_session: Session, user_id: UUID, auto_playback: bool
) -> None:
    """Update user's voice auto-playback setting."""
    db_session.execute(
        update(User).where(User.id == user_id).values(voice_auto_playback=auto_playback)
    )
    db_session.commit()


def update_user_voice_playback_speed(
    db_session: Session, user_id: UUID, speed: float
) -> None:
    """Update user's voice playback speed setting."""
    # Clamp to valid range
    speed = max(0.5, min(2.0, speed))
    db_session.execute(
        update(User).where(User.id == user_id).values(voice_playback_speed=speed)
    )
    db_session.commit()


def update_user_preferred_voice(
    db_session: Session, user_id: UUID, voice: str | None
) -> None:
    """Update user's preferred voice setting."""
    db_session.execute(
        update(User).where(User.id == user_id).values(preferred_voice=voice)
    )
    db_session.commit()


def update_user_voice_settings(
    db_session: Session,
    user_id: UUID,
    auto_send: bool | None = None,
    auto_playback: bool | None = None,
    playback_speed: float | None = None,
    preferred_voice: str | None = None,
) -> None:
    """Update user's voice settings. Only updates fields that are not None."""
    values: dict[str, Any] = {}

    if auto_send is not None:
        values["voice_auto_send"] = auto_send
    if auto_playback is not None:
        values["voice_auto_playback"] = auto_playback
    if playback_speed is not None:
        values["voice_playback_speed"] = max(0.5, min(2.0, playback_speed))
    if preferred_voice is not None:
        values["preferred_voice"] = preferred_voice

    if values:
        db_session.execute(update(User).where(User.id == user_id).values(**values))
        db_session.commit()
