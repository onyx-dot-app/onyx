"""_resolve_api_key resolves a masked key (admin editing a saved provider) back
to the stored key — looked up by the reliable provider_id. A freshly typed key
is used as-is, and the stored key is only returned when the request's api_base
matches the stored one."""

from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

from sqlalchemy.orm import Session

from onyx.server.manage.llm.api import _resolve_api_key

_STORED = "v1.Crealsecretkeyda0A"
_MASKED = "v1.C****da0A"  # _mask_string(_STORED)
_BASE = "https://api.tokenfactory.nebius.com/v1"


def _provider() -> SimpleNamespace:
    return SimpleNamespace(
        api_base=_BASE,
        api_key=SimpleNamespace(get_value=lambda **_: _STORED),
    )


def test_masked_key_resolves_to_stored_by_id() -> None:
    with patch(
        "onyx.server.manage.llm.api.fetch_existing_llm_provider_by_id",
        return_value=_provider(),
    ):
        assert (
            _resolve_api_key(_MASKED, 7, _BASE, db_session=cast(Session, None))
            == _STORED
        )


def test_fresh_key_used_as_is() -> None:
    with patch(
        "onyx.server.manage.llm.api.fetch_existing_llm_provider_by_id",
        return_value=_provider(),
    ):
        assert (
            _resolve_api_key(
                "sk-brand-new-key-123456", 7, _BASE, db_session=cast(Session, None)
            )
            == "sk-brand-new-key-123456"
        )


def test_no_provider_id_returns_input() -> None:
    assert (
        _resolve_api_key(_MASKED, None, _BASE, db_session=cast(Session, None))
        == _MASKED
    )


def test_mismatched_api_base_returns_input() -> None:
    with patch(
        "onyx.server.manage.llm.api.fetch_existing_llm_provider_by_id",
        return_value=_provider(),
    ):
        assert (
            _resolve_api_key(
                _MASKED,
                7,
                "https://other.example/v1",
                db_session=cast(Session, None),
            )
            == _MASKED
        )
