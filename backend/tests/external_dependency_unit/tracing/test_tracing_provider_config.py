"""External-dependency-unit tests for tracing provider config persistence/resolution.

Exercises the real Postgres-backed encrypted storage and the DB-wins-else-env
resolution used by the live tracing processors.
"""

from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session

from onyx.db.tracing import (
    delete_tracing_provider,
    fetch_tracing_provider,
    upsert_tracing_provider,
)
from onyx.server.manage.api_token.models import ExistingApiToken, NewApiToken
from onyx.tracing import provider_config
from onyx.tracing.provider_config import resolve_effective_tracing_config
from shared_configs.enums import TracingProviderType


@pytest.fixture(autouse=True)
def clean_tracing_table(db_session: Session) -> Generator[None, None, None]:
    """Ensure a clean tracing_provider_config table around each test."""
    for provider in TracingProviderType:
        delete_tracing_provider(provider, db_session)
    db_session.commit()
    yield
    for provider in TracingProviderType:
        delete_tracing_provider(provider, db_session)
    db_session.commit()


def test_encrypted_roundtrip_and_masking(db_session: Session) -> None:
    upsert_tracing_provider(
        provider_type=TracingProviderType.BRAINTRUST,
        api_key=NewApiToken(value="bt-secret-key"),
        config={"project": "MyProject"},
        db_session=db_session,
    )
    db_session.commit()

    row = fetch_tracing_provider(TracingProviderType.BRAINTRUST, db_session)
    assert row is not None
    assert row.api_key is not None
    assert row.api_key.get_value(apply_mask=False) == "bt-secret-key"
    masked = row.api_key.get_value(apply_mask=True)
    assert masked != "bt-secret-key"
    assert "bt-secret-key" not in masked


def test_existing_token_keeps_stored_key(db_session: Session) -> None:
    upsert_tracing_provider(
        provider_type=TracingProviderType.BRAINTRUST,
        api_key=NewApiToken(value="original-key"),
        config={"project": "P1"},
        db_session=db_session,
    )
    db_session.commit()
    original = fetch_tracing_provider(TracingProviderType.BRAINTRUST, db_session)
    assert original is not None and original.api_token_id is not None
    token_id = original.api_token_id

    # Update non-secret config and keep the key the row already has.
    upsert_tracing_provider(
        provider_type=TracingProviderType.BRAINTRUST,
        api_key=ExistingApiToken(id=token_id),
        config={"project": "P2"},
        db_session=db_session,
    )
    db_session.commit()

    row = fetch_tracing_provider(TracingProviderType.BRAINTRUST, db_session)
    assert row is not None
    assert row.api_key is not None
    assert row.api_token_id == token_id
    assert row.api_key.get_value(apply_mask=False) == "original-key"
    assert (row.config or {}).get("project") == "P2"


def test_env_fallback_when_no_row(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(provider_config, "BRAINTRUST_API_KEY", "env-key")
    monkeypatch.setattr(provider_config, "BRAINTRUST_PROJECT", "EnvProject")

    config = resolve_effective_tracing_config()
    assert config.braintrust is not None
    assert config.braintrust.api_key == "env-key"
    assert config.braintrust.project == "EnvProject"


def test_db_row_overrides_env(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(provider_config, "BRAINTRUST_API_KEY", "env-key")
    monkeypatch.setattr(provider_config, "BRAINTRUST_PROJECT", "EnvProject")

    upsert_tracing_provider(
        provider_type=TracingProviderType.BRAINTRUST,
        api_key=NewApiToken(value="db-key"),
        config={"project": "DbProject"},
        db_session=db_session,
    )
    db_session.commit()

    config = resolve_effective_tracing_config()
    assert config.braintrust is not None
    assert config.braintrust.api_key == "db-key"
    assert config.braintrust.project == "DbProject"


def test_disabled_row_turns_provider_off_even_with_env(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(provider_config, "BRAINTRUST_API_KEY", "env-key")

    upsert_tracing_provider(
        provider_type=TracingProviderType.BRAINTRUST,
        api_key=NewApiToken(value="db-key"),
        config={"project": "DbProject"},
        enabled=False,
        db_session=db_session,
    )
    db_session.commit()

    config = resolve_effective_tracing_config()
    assert config.braintrust is None


def test_langfuse_requires_both_keys(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(provider_config, "LANGFUSE_SECRET_KEY", "")
    monkeypatch.setattr(provider_config, "LANGFUSE_PUBLIC_KEY", "")

    # Secret key present but public key missing from config -> not enabled.
    upsert_tracing_provider(
        provider_type=TracingProviderType.LANGFUSE,
        api_key=NewApiToken(value="lf-secret"),
        config={"host": "https://cloud.langfuse.com"},
        db_session=db_session,
    )
    db_session.commit()
    assert resolve_effective_tracing_config().langfuse is None
    row = fetch_tracing_provider(TracingProviderType.LANGFUSE, db_session)
    assert row is not None and row.api_token_id is not None

    # Add the public key -> now enabled.
    upsert_tracing_provider(
        provider_type=TracingProviderType.LANGFUSE,
        api_key=ExistingApiToken(id=row.api_token_id),
        config={"public_key": "lf-public", "host": "https://cloud.langfuse.com"},
        db_session=db_session,
    )
    db_session.commit()

    config = resolve_effective_tracing_config()
    assert config.langfuse is not None
    assert config.langfuse.secret_key == "lf-secret"
    assert config.langfuse.public_key == "lf-public"
    assert config.langfuse.host == "https://cloud.langfuse.com"
