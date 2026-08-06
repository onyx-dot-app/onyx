"""Unit tests for the operator-forced document-set scope.

Covers the name verifier (disabled when multitenant/unset, logs an error for a
missing name) and that _build_index_filters applies the scope only when the
Search-UI force flag is set. The DB is mocked so these run without external deps.
"""

from types import SimpleNamespace
from typing import Any, Iterator, cast

import pytest
from sqlalchemy.orm import Session

import onyx.context.search.forced_document_set as fds
import onyx.context.search.pipeline as pipeline
from onyx.context.search.models import IndexFilters
from onyx.db.models import User

_DB = cast(Session, object())


@pytest.fixture(autouse=True)
def _single_tenant(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(fds, "MULTI_TENANT", False)
    yield


def _patch_names_and_db(
    monkeypatch: pytest.MonkeyPatch, names: list[str], existing: list[str]
) -> None:
    monkeypatch.setattr(fds, "FORCED_DOCUMENT_SET_NAMES", names)
    monkeypatch.setattr(
        fds,
        "get_document_sets_by_name",
        lambda _db, _names: [SimpleNamespace(name=n) for n in existing],
    )


def test_disabled_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_names_and_db(monkeypatch, names=[], existing=[])
    assert fds.get_forced_document_set_names(_DB) is None


def test_disabled_in_multitenant(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fds, "MULTI_TENANT", True)
    _patch_names_and_db(monkeypatch, names=["HR"], existing=["HR"])
    assert fds.get_forced_document_set_names(_DB) is None


def test_returns_configured_names(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_names_and_db(monkeypatch, names=["HR", "Legal"], existing=["HR", "Legal"])
    assert fds.get_forced_document_set_names(_DB) == ["HR", "Legal"]


def test_missing_name_is_logged_but_still_returned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_names_and_db(monkeypatch, names=["HR", "Typo"], existing=["HR"])
    errors: list[Any] = []
    monkeypatch.setattr(fds.logger, "error", lambda msg, *a: errors.append((msg, a)))

    names = fds.get_forced_document_set_names(_DB)

    # Missing names are still returned — they just match nothing (fail-closed).
    assert names == ["HR", "Typo"]
    assert errors and "Typo" in str(errors[0]), "a missing name must log an error"


def _build_filters(monkeypatch: pytest.MonkeyPatch, *, force: bool) -> IndexFilters:
    """Call _build_index_filters with the resolver stubbed to return ["Eng"]."""
    monkeypatch.setattr(pipeline, "get_forced_document_set_names", lambda _db: ["Eng"])
    return pipeline._build_index_filters(
        user_provided_filters=None,
        user=cast(User, SimpleNamespace(is_anonymous=False)),
        project_id_filter=None,
        persona_id_filter=None,
        persona_document_sets=None,
        persona_time_cutoff=None,
        db_session=None,
        bypass_acl=True,
        force_configured_document_set_scope=force,
    )


def test_build_index_filters_applies_scope_with_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Search UI path (flag on) → the forced scope is set on IndexFilters."""
    filters = _build_filters(monkeypatch, force=True)
    assert filters.forced_document_set == ["Eng"]


def test_build_index_filters_no_scope_without_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Chat / other callers (flag off) → the forced scope is NOT applied."""
    filters = _build_filters(monkeypatch, force=False)
    assert filters.forced_document_set is None
