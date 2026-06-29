"""Drives the /admin/tracing endpoint handlers in-process against the real DB.

The handlers are invoked directly (passing a real session); auth is enforced by
FastAPI dependencies at the HTTP layer and is out of scope here.
"""

from collections.abc import Generator
from typing import cast

import pytest
from sqlalchemy.orm import Session

from onyx.db.models import User
from onyx.db.tracing import delete_tracing_provider
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.tracing import api as tracing_api
from onyx.server.manage.tracing.api import adopt_env_tracing_provider
from onyx.server.manage.tracing.api import disconnect_tracing_provider
from onyx.server.manage.tracing.api import list_tracing_providers
from onyx.server.manage.tracing.api import upsert_tracing_provider_endpoint
from onyx.server.manage.tracing.models import TracingProviderTestRequest
from onyx.server.manage.tracing.models import TracingProviderUpsertRequest
from onyx.tracing import provider_config
from shared_configs.enums import TracingProviderType

# Handlers tolerate a None user (updated_by becomes null); cast to satisfy typing.
_NO_USER = cast(User, None)


@pytest.fixture(autouse=True)
def clean_tracing_table(db_session: Session) -> Generator[None, None, None]:
    for provider in TracingProviderType:
        delete_tracing_provider(provider, db_session)
    db_session.commit()
    yield
    for provider in TracingProviderType:
        delete_tracing_provider(provider, db_session)
    db_session.commit()


def _view(views: list, provider_type: TracingProviderType):
    return next(v for v in views if v.provider_type == provider_type)


def test_connect_then_list_shows_db_masked(db_session: Session) -> None:
    upsert_tracing_provider_endpoint(
        TracingProviderUpsertRequest(
            provider_type=TracingProviderType.BRAINTRUST,
            api_key="bt-secret",
            api_key_changed=True,
            config={"project": "MyProject"},
        ),
        _NO_USER,
        db_session,
    )

    views = list_tracing_providers(_NO_USER, db_session)
    braintrust = _view(views, TracingProviderType.BRAINTRUST)
    assert braintrust.connected is True
    assert braintrust.source == "db"
    assert braintrust.config == {"project": "MyProject"}
    assert braintrust.masked_api_key and "bt-secret" not in braintrust.masked_api_key

    langfuse = _view(views, TracingProviderType.LANGFUSE)
    assert langfuse.connected is False
    assert langfuse.source == "none"


def test_disconnect_removes_db_row(db_session: Session) -> None:
    upsert_tracing_provider_endpoint(
        TracingProviderUpsertRequest(
            provider_type=TracingProviderType.BRAINTRUST,
            api_key="bt-secret",
            api_key_changed=True,
            config={"project": "P"},
        ),
        _NO_USER,
        db_session,
    )

    view = disconnect_tracing_provider(
        TracingProviderType.BRAINTRUST, _NO_USER, db_session
    )
    assert view.source == "none"
    assert view.connected is False


def test_validate_endpoint_rejects_missing_key(db_session: Session) -> None:
    with pytest.raises(OnyxError):
        tracing_api.test_tracing_provider(
            TracingProviderTestRequest(provider_type=TracingProviderType.BRAINTRUST),
            _NO_USER,
            db_session,
        )


def test_adopt_env_without_env_raises(db_session: Session) -> None:
    with pytest.raises(OnyxError):
        adopt_env_tracing_provider(TracingProviderType.BRAINTRUST, _NO_USER, db_session)


def test_adopt_env_copies_into_db_row(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(provider_config, "BRAINTRUST_API_KEY", "env-key")
    monkeypatch.setattr(provider_config, "BRAINTRUST_PROJECT", "EnvProject")

    view = adopt_env_tracing_provider(
        TracingProviderType.BRAINTRUST, _NO_USER, db_session
    )
    assert view.source == "db"
    assert view.connected is True
    assert view.config == {"project": "EnvProject"}


def test_multi_tenant_gate_rejects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tracing_api, "MULTI_TENANT", True)
    with pytest.raises(OnyxError):
        tracing_api._reject_if_multi_tenant()
