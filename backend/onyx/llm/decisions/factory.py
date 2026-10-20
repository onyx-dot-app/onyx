from functools import partial

from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.voice import fetch_voice_provider_by_id
from onyx.llm.decisions.client import DecisionClient
from onyx.llm.decisions.models import DecisionProvider
from onyx.voice.interface import normalize_provider_type
from onyx.voice.providers.zoom import build_zoom_scribe_jwt


def validate_zoom_voice_provider(
    db_session: Session, provider_id: int, *, for_update: bool = False
) -> None:
    provider = fetch_voice_provider_by_id(
        db_session, provider_id, for_update=for_update
    )
    if provider is None or normalize_provider_type(provider.provider_type) != "zoom":
        raise ValueError("Select an existing Zoom Scribe connection")
    if not provider.api_key or not provider.api_secret:
        raise ValueError("The Zoom Scribe connection requires an API key and secret")


def _zoom_decision_token(provider_id: int) -> str:
    with get_session_with_current_tenant() as db_session:
        validate_zoom_voice_provider(db_session, provider_id)
        provider = fetch_voice_provider_by_id(db_session, provider_id)
        if provider is None or provider.api_key is None or provider.api_secret is None:
            raise ValueError("The Zoom Scribe credentials are no longer available")
        return build_zoom_scribe_jwt(
            provider.api_key.get_value(apply_mask=False),
            provider.api_secret.get_value(apply_mask=False),
        )


def build_decision_client(
    *,
    provider: str,
    model: str,
    api_key: str | None,
    api_base: str | None = None,
    zoom_voice_provider_id: int | None = None,
    extra_headers: dict[str, str] | None = None,
) -> DecisionClient:
    if zoom_voice_provider_id is not None and provider != DecisionProvider.ZOOM_AI:
        raise ValueError("Only Zoom Decisions can link a Zoom Scribe connection")
    return DecisionClient(
        provider=DecisionProvider(provider),
        model=model,
        api_key=api_key or "",
        api_base=api_base,
        extra_headers=extra_headers,
        api_key_resolver=(
            partial(_zoom_decision_token, zoom_voice_provider_id)
            if zoom_voice_provider_id is not None
            else None
        ),
    )
