"""The bundled ``zendesk_api.py`` sandbox helper: the pure argument and
response handling the subcommands rest on. The helper is a standalone script
under the skills dir (not an importable package), so load it by path. These
tests require no network and no onyx imports."""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_HELPER = (
    Path(__file__).resolve().parents[3]
    / "onyx/skills/builtin"
    / "zendesk/zendesk_api.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("zendesk_api", _HELPER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


zendesk = _load()

_BASE = "https://acme.zendesk.com"


@pytest.mark.parametrize(
    "value",
    ["acme", "ACME", "acme.zendesk.com", "https://acme.zendesk.com/agent/filters"],
)
def test_site_accepts_a_subdomain_or_an_account_url(value: str) -> None:
    assert zendesk._site_base_url(value) == _BASE


@pytest.mark.parametrize(
    "value", ["", "acme corp", "acme.example.com", "https://evil.test/acme"]
)
def test_site_rejects_anything_but_a_zendesk_account(value: str) -> None:
    """The base URL is what the egress proxy matches to inject this account's
    token, so the helper refuses to address anywhere else."""
    with pytest.raises(argparse.ArgumentTypeError):
        zendesk._site_base_url(value)


def test_since_accepts_an_epoch_or_an_iso_instant() -> None:
    """Zendesk's incremental export takes a unix timestamp; an ISO instant is
    what the agent is far more likely to have, so both work."""
    assert zendesk._epoch_seconds("1759276800") == 1759276800
    iso = zendesk._epoch_seconds("2026-10-01T00:00:00Z")
    # A naive instant is read as UTC, so the two agree.
    assert iso == zendesk._epoch_seconds("2026-10-01T00:00:00")


def test_since_rejects_prose() -> None:
    with pytest.raises(zendesk.ZendeskError):
        zendesk._epoch_seconds("yesterday")


@pytest.mark.parametrize(
    "page, expected",
    [
        # Offset paging.
        (
            {"next_page": f"{_BASE}/api/v2/tickets.json?page=2"},
            f"{_BASE}/api/v2/tickets.json?page=2",
        ),
        # Cursor paging stops on meta.has_more, not on a missing link.
        (
            {"links": {"next": f"{_BASE}/api/v2/x"}, "meta": {"has_more": True}},
            f"{_BASE}/api/v2/x",
        ),
        ({"links": {"next": f"{_BASE}/api/v2/x"}, "meta": {"has_more": False}}, None),
        # Incremental export stops on end_of_stream.
        (
            {"after_url": f"{_BASE}/api/v2/x", "end_of_stream": False},
            f"{_BASE}/api/v2/x",
        ),
        ({"after_url": f"{_BASE}/api/v2/x", "end_of_stream": True}, None),
        # A link off this account is not ours to follow.
        ({"next_page": "https://evil.test/api/v2/x"}, None),
        ({"next_page": f"{_BASE}.evil.test/api/v2/x"}, None),
        ({}, None),
    ],
)
def test_next_page_url_covers_every_paging_shape(
    page: dict[str, object], expected: str | None
) -> None:
    assert zendesk._next_page_url(page, _BASE) == expected


def test_changed_requires_exactly_one_starting_point() -> None:
    """A resuming export must say where it resumes from — a `--since` and a
    `--cursor` together would silently ignore one of them."""
    parser = zendesk._build_parser()
    for argv in (
        ["--site", "acme", "changed"],
        ["--site", "acme", "changed", "--since", "1759276800", "--cursor", "c"],
    ):
        with pytest.raises(zendesk.ZendeskError):
            zendesk._incremental_tickets(
                "https://acme.zendesk.com", parser.parse_args(argv)
            )


def test_changed_stops_on_a_page_boundary_and_returns_the_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cursor must be safe to resume from: every ticket before it is in
    this result, so the walk may never stop part-way through a page."""
    pages = [
        {
            "tickets": [{"id": 1}, {"id": 2}],
            "after_cursor": "c1",
            "after_url": f"{_BASE}/api/v2/incremental/tickets/cursor.json?cursor=c1",
            "end_of_stream": False,
        },
        {"tickets": [{"id": 3}], "after_cursor": "c2", "end_of_stream": True},
    ]
    calls: list[str] = []

    def _fake_request(
        _base: str, _method: str, path: str, _body: object = None
    ) -> object:
        calls.append(path)
        return pages[len(calls) - 1]

    monkeypatch.setattr(zendesk, "_request", _fake_request)
    args = zendesk._build_parser().parse_args(
        ["--site", "acme", "changed", "--since", "1759276800", "--limit", "1"]
    )
    result = zendesk._incremental_tickets(_BASE, args)

    # --limit 1 is a floor: the first page is consumed whole, then the walk stops.
    assert result["count"] == 2
    assert result["cursor"] == "c1"
    assert result["end_of_stream"] is False
    assert len(calls) == 1


def test_changed_resumes_from_a_cursor(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []

    def _fake_request(
        _base: str, _method: str, path: str, _body: object = None
    ) -> object:
        captured.append(path)
        return {"tickets": [], "after_cursor": "c9", "end_of_stream": True}

    monkeypatch.setattr(zendesk, "_request", _fake_request)
    args = zendesk._build_parser().parse_args(
        ["--site", "acme", "changed", "--cursor", "c8"]
    )
    result = zendesk._incremental_tickets(_BASE, args)
    assert "cursor=c8" in captured[0]
    assert "start_time" not in captured[0]
    assert result["cursor"] == "c9"
    assert result["end_of_stream"] is True


def test_ids_are_percent_encoded_into_the_path() -> None:
    assert (
        zendesk._path("/api/v2/tickets/{0}.json", "12/3?x")
        == "/api/v2/tickets/12%2F3%3Fx.json"
    )


def test_set_pairs_keep_json_types() -> None:
    """`--set assignee_id=123` must send a number, not the string "123"."""
    assert zendesk._pairs(["status=solved", "assignee_id=123", 'tags=["a"]']) == {
        "status": "solved",
        "assignee_id": 123,
        "tags": ["a"],
    }


def test_set_pairs_reject_a_bare_token() -> None:
    with pytest.raises(zendesk.ZendeskError):
        zendesk._pairs(["solved"])


def test_prune_keeps_false_and_zero() -> None:
    """Empty values are noise; `false` and `0` carry signal."""
    assert zendesk._prune({"a": None, "b": "", "c": [], "d": False, "e": 0}) == {
        "d": False,
        "e": 0,
    }


def test_search_only_slims_ticket_hits() -> None:
    """Search spans tickets, users and organizations. Cutting a user down to
    the ticket field list would drop the `name` and `email` that identify it."""
    user = {"result_type": "user", "id": 7, "name": "Ada", "email": "a@b.co"}
    assert zendesk._slim_result(user, full=False) == user

    ticket = {"result_type": "ticket", "id": 1, "subject": "s", "ticket_form_id": 9}
    assert zendesk._slim_result(ticket, full=False) == {
        "id": 1,
        "subject": "s",
        "result_type": "ticket",
    }

    # A payload with no result_type (a plain ticket list) still slims.
    assert zendesk._slim_result({"id": 1, "ticket_form_id": 9}, full=False) == {"id": 1}


def test_search_keeps_result_type_on_a_slimmed_ticket() -> None:
    """`result_type` is what tells a mixed result set apart, so it survives the
    ticket field list."""
    hit = {"result_type": "ticket", "id": 1, "subject": "s", "ticket_form_id": 9}
    assert zendesk._slim_result(hit, full=False) == {
        "id": 1,
        "subject": "s",
        "result_type": "ticket",
    }


def test_slim_keeps_the_readable_subset_unless_full() -> None:
    ticket = {"id": 1, "subject": "s", "forum_topic_id": None, "ticket_form_id": 9}
    assert zendesk._slim(ticket, full=False) == {"id": 1, "subject": "s"}
    assert zendesk._slim(ticket, full=True) == ticket
