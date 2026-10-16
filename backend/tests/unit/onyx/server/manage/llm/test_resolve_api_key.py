"""_resolve_api_key returns the raw key a model-fetch request names. A typed
key is used as-is. A saved key is read through the API token, with the edited
provider's own token passed as the current one."""

from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session

from onyx.server.manage.api_token.models import ExistingApiToken, NewApiToken
from onyx.server.manage.llm.api import _resolve_api_key

_BASE = "https://api.tokenfactory.nebius.com/v1"
_PLATFORM = "nebius_tokenfactory"


def test_new_key_used_as_is() -> None:
    assert (
        _resolve_api_key(
            NewApiToken(value="sk-brand-new-key-123456"),
            None,
            _BASE,
            _PLATFORM,
            db_session=cast(Session, None),
        )
        == "sk-brand-new-key-123456"
    )


def test_no_key_returns_none() -> None:
    assert (
        _resolve_api_key(None, None, _BASE, _PLATFORM, db_session=cast(Session, None))
        is None
    )


def test_saved_key_passes_provider_token_as_current() -> None:
    peek = MagicMock(return_value="stored-key")
    with (
        patch(
            "onyx.server.manage.llm.api.fetch_existing_llm_provider_by_id",
            return_value=SimpleNamespace(api_token_id=42),
        ),
        patch("onyx.server.manage.llm.api.peek_api_token_value", peek),
    ):
        assert (
            _resolve_api_key(
                ExistingApiToken(id=42),
                7,
                _BASE,
                _PLATFORM,
                db_session=cast(Session, None),
            )
            == "stored-key"
        )
    assert peek.call_args.kwargs == {
        "platform": _PLATFORM,
        "base_url": _BASE,
        "current_token_id": 42,
    }
