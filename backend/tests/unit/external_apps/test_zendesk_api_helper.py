"""The bundled ``zendesk_api.py`` sandbox helper: the pure argument and
response handling the subcommands rest on. A standalone script, not an
importable package, so load it by path. No network, no onyx imports."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_SKILL_DIR = Path(__file__).resolve().parents[3] / "onyx/skills/builtin" / "zendesk"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "zendesk_api", _SKILL_DIR / "zendesk_api.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


zendesk = _load()

_BASE = "https://acme.zendesk.com"


def test_base_url_is_read_from_the_rendered_account_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One workspace connects one account, so the helper takes no account
    argument — the push writes it beside the script."""
    account = tmp_path / "account.txt"
    account.write_text("https://acme.zendesk.com\n")
    monkeypatch.setattr(zendesk, "_ACCOUNT_FILE", account)
    assert zendesk._base_url() == _BASE


@pytest.mark.parametrize("contents", ["", "   ", "acme", "ftp://acme.zendesk.com"])
def test_an_unconfigured_account_is_an_input_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, contents: str
) -> None:
    """A half-configured app must say so, not emit a confusing network error."""
    account = tmp_path / "account.txt"
    account.write_text(contents)
    monkeypatch.setattr(zendesk, "_ACCOUNT_FILE", account)
    with pytest.raises(zendesk.ZendeskError):
        zendesk._base_url()


def test_a_missing_account_file_is_an_input_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(zendesk, "_ACCOUNT_FILE", tmp_path / "nope.txt")
    with pytest.raises(zendesk.ZendeskError):
        zendesk._base_url()


def test_the_account_template_renders_the_providers_base_url() -> None:
    """The template beside the script is what the push fills in."""
    template = (_SKILL_DIR / "account.txt.template").read_text()
    assert template.strip() == "{{APP:base_url}}"


def test_since_accepts_an_epoch_or_an_iso_instant() -> None:
    """The export takes a unix timestamp; an agent is likelier to have ISO."""
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
    """Both together would silently ignore one of them."""
    parser = zendesk._build_parser()
    for argv in (
        ["changed"],
        ["changed", "--since", "1759276800", "--cursor", "c"],
    ):
        with pytest.raises(zendesk.ZendeskError):
            zendesk._incremental_tickets(
                "https://acme.zendesk.com", parser.parse_args(argv)
            )


def test_changed_stops_on_a_page_boundary_and_returns_the_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cursor must be safe to resume from, so the walk never stops
    part-way through a page."""
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
        ["changed", "--since", "1759276800", "--limit", "1"]
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
    args = zendesk._build_parser().parse_args(["changed", "--cursor", "c8"])
    result = zendesk._incremental_tickets(_BASE, args)
    assert "cursor=c8" in captured[0]
    assert "start_time" not in captured[0]
    assert result["cursor"] == "c9"
    assert result["end_of_stream"] is True


def test_a_page_that_never_ends_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty page can still carry a next link; the walk must stop."""
    calls = 0

    def _fake_request(
        _base: str, _method: str, _path: str, _body: object = None
    ) -> object:
        nonlocal calls
        calls += 1
        return {
            "tickets": [],
            "after_cursor": "c",
            "after_url": f"{_BASE}/api/v2/incremental/tickets/cursor.json?cursor=c",
            "end_of_stream": False,
        }

    monkeypatch.setattr(zendesk, "_request", _fake_request)
    args = zendesk._build_parser().parse_args(["changed", "--since", "1759276800"])
    result = zendesk._incremental_tickets(_BASE, args)
    assert calls == zendesk._MAX_PAGES
    assert result["count"] == 0
    assert result["cursor"] == "c"


@pytest.mark.parametrize(
    "argv, expected_method",
    [
        (["tag", "1", "--tags", "a"], "PUT"),
        (["tag", "1", "--tags", "a", "--replace"], "POST"),
    ],
)
def test_tag_uses_zendesks_reversed_tag_methods(
    monkeypatch: pytest.MonkeyPatch, argv: list[str], expected_method: str
) -> None:
    """PUT adds, POST replaces. Backwards, `tag` erases a ticket's tags."""
    seen: list[str] = []

    def _fake_request(
        _base: str, method: str, _path: str, _body: object = None
    ) -> object:
        seen.append(method)
        return {"tags": ["a"]}

    monkeypatch.setattr(zendesk, "_request", _fake_request)
    result = zendesk._dispatch_write(zendesk._build_parser().parse_args(argv), _BASE)
    assert seen == [expected_method]
    assert result == {"ok": True, "tags": ["a"]}


def test_changed_rejects_a_blank_cursor() -> None:
    """It passes the "exactly one" check but names no position."""
    args = zendesk._build_parser().parse_args(["changed", "--cursor", ""])
    with pytest.raises(zendesk.ZendeskError):
        zendesk._incremental_tickets(_BASE, args)


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
    """`false` and `0` carry signal."""
    assert zendesk._prune({"a": None, "b": "", "c": [], "d": False, "e": 0}) == {
        "d": False,
        "e": 0,
    }


def test_search_only_slims_ticket_hits() -> None:
    """Cutting a user to the ticket field list drops its `name` and `email`."""
    user = {"result_type": "user", "id": 7, "name": "Ada", "email": "a@b.co"}
    assert zendesk._slim(user, full=False) == user
    organization = {"result_type": "organization", "id": 8, "name": "Acme"}
    assert zendesk._slim(organization, full=False) == organization

    ticket = {"result_type": "ticket", "id": 1, "subject": "s", "ticket_form_id": 9}
    assert zendesk._slim(ticket, full=False) == {
        "id": 1,
        "subject": "s",
        "result_type": "ticket",
    }

    assert zendesk._slim(ticket, full=True) == ticket


def test_slim_keeps_the_readable_subset_unless_full() -> None:
    ticket = {"id": 1, "subject": "s", "forum_topic_id": None, "ticket_form_id": 9}
    assert zendesk._slim(ticket, full=False) == {"id": 1, "subject": "s"}
    assert zendesk._slim(ticket, full=True) == ticket
