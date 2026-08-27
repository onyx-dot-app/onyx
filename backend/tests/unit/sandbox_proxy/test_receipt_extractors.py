"""Unit tests for the receipt extractors.

Pure request/response parsing: destinations, deep links built from provider
ids, provider-level verdicts hiding inside transport successes, and the
coalescing keys for the Slack upload flow. Malformed bodies must refine
nothing rather than raise.
"""

import json
from urllib.parse import urlencode

import pytest

from onyx.db.enums import ReceiptStatus
from onyx.sandbox_proxy.receipt_extractors import (
    request_facts,
    response_facts,
    slack_upload_key,
    slack_upload_url_token,
    upload_url_token,
)


def _body(payload: dict) -> bytes:
    return json.dumps(payload).encode()


def test_slack_message_request_names_the_channel() -> None:
    facts = request_facts("slack.messages.write", _body({"channel": "exec-team"}))
    assert facts.destination == "#exec-team"
    assert (
        request_facts("slack.messages.write", _body({"channel": "#ops"})).destination
        == "#ops"
    )


def test_slack_conversation_id_is_not_hash_prefixed() -> None:
    facts = request_facts("slack.messages.write", _body({"channel": "C08ABCDEF"}))
    assert facts.destination == "C08ABCDEF"


def test_form_encoded_request_bodies_parse() -> None:
    # slack_sdk sends form-encoded bodies, with nested values JSON-serialized.
    message = urlencode({"channel": "exec-team", "text": "hi"}).encode()
    assert request_facts("slack.messages.write", message).destination == "#exec-team"
    complete = urlencode(
        {"files": json.dumps([{"id": "F42", "title": "deck"}])}
    ).encode()
    facts = request_facts("slack.files.write", complete)
    assert facts.operation_key == "slack.files.write:F42"


def test_slack_ok_false_overrides_the_transport_verdict() -> None:
    facts = response_facts(
        "slack.messages.write", _body({"ok": False, "error": "channel_not_found"})
    )
    assert facts.status_override is ReceiptStatus.FAILED
    assert facts.link is None


def test_slack_message_link_built_from_channel_and_ts() -> None:
    facts = response_facts(
        "slack.messages.write",
        _body({"ok": True, "channel": "C0123", "ts": "1712.3456"}),
    )
    assert facts.link == "https://slack.com/archives/C0123/p17123456"


def test_unsafe_provider_ids_refine_nothing() -> None:
    evil = response_facts(
        "slack.messages.write",
        _body({"ok": True, "channel": "C0123/../evil", "ts": "1712.3456"}),
    )
    assert evil.link is None
    assert response_facts("gdrive.files.create", _body({"id": "a?b#c"})).link is None


def test_slack_upload_flow_keys_coalesce() -> None:
    step_one = {
        "ok": True,
        "file_id": "F999",
        "upload_url": "https://files.slack.com/upload/v1/tok123",
    }
    assert slack_upload_key(step_one) == "slack.files.write:F999"
    assert slack_upload_url_token(step_one) == "tok123"
    # Step three carries the same file id in its request.
    facts = request_facts(
        "slack.files.write", _body({"files": [{"id": "F999", "title": "deck"}]})
    )
    assert facts.operation_key == "slack.files.write:F999"
    # Step one's response reveals the same key for the keyless first receipt.
    assert (
        response_facts("slack.files.write", _body(step_one)).operation_key
        == "slack.files.write:F999"
    )


def test_upload_url_token_shared_derivation_strips_queries() -> None:
    # Writer side (step one's upload_url) and reader side (step two's request
    # path) must agree even when a query string rides along.
    assert upload_url_token("https://files.slack.com/upload/v1/tok?x=1") == "tok"
    assert upload_url_token("/upload/v1/tok?x=1") == "tok"
    assert upload_url_token("/upload/v1/tok/") == "tok"
    assert upload_url_token("token-only") is None


@pytest.mark.parametrize(
    "mime,prefix",
    [
        ("application/vnd.google-apps.document", "https://docs.google.com/document/d/"),
        (
            "application/vnd.google-apps.spreadsheet",
            "https://docs.google.com/spreadsheets/d/",
        ),
        (
            "application/vnd.google-apps.presentation",
            "https://docs.google.com/presentation/d/",
        ),
        ("application/pdf", "https://drive.google.com/file/d/"),
    ],
)
def test_gdrive_links_follow_the_mime_type(mime: str, prefix: str) -> None:
    facts = response_facts(
        "gdrive.files.create", _body({"id": "abc123", "mimeType": mime})
    )
    assert facts.link == f"{prefix}abc123"


def test_gmail_send_and_draft_shapes_both_link() -> None:
    sent = response_facts("gmail.messages.send", _body({"id": "m1", "threadId": "t1"}))
    assert sent.link == "https://mail.google.com/mail/u/0/#all/m1"
    draft = response_facts(
        "gmail.drafts.create", _body({"id": "d1", "message": {"id": "m2"}})
    )
    assert draft.link == "https://mail.google.com/mail/u/0/#all/m2"


def test_linear_errors_fail_and_only_shaped_urls_pass() -> None:
    failed = response_facts(
        "linear.issues.create", _body({"errors": [{"message": "boom"}]})
    )
    assert failed.status_override is ReceiptStatus.FAILED

    good = response_facts(
        "linear.issues.create",
        _body(
            {
                "data": {
                    "issueCreate": {
                        "issue": {"url": "https://linear.app/acme/issue/ENG-42/title"}
                    }
                }
            }
        ),
    )
    assert good.link == "https://linear.app/acme/issue/ENG-42/title"


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/x",
        "https://linear.app/acme/issue/ENG-42?redirect=https://evil.example",
        "https://linear.app/acme/issue/ENG-42/title#fragment",
        "https://linear.app/acme/issue/ENG-42/../../x",
        "https://linear.app/acme/issue/" + "a" * 600,
    ],
)
def test_linear_rejects_unshaped_urls(url: str) -> None:
    facts = response_facts(
        "linear.issues.create",
        _body({"data": {"issueCreate": {"issue": {"url": url}}}}),
    )
    assert facts.link is None


def test_linear_url_found_inside_a_list_payload() -> None:
    facts = response_facts(
        "linear.issues.create",
        _body(
            {
                "data": {
                    "issueBatchCreate": {
                        "issues": [{"url": "https://linear.app/acme/issue/ENG-1/first"}]
                    }
                }
            }
        ),
    )
    assert facts.link == "https://linear.app/acme/issue/ENG-1/first"


def test_malformed_bodies_refine_nothing() -> None:
    for raw in (None, b"", b"{", b"[1,2]", b"\xff\xfe"):
        assert request_facts("slack.messages.write", raw).destination is None
        facts = response_facts("slack.messages.write", raw)
        assert facts.link is None and facts.status_override is None


def test_unknown_actions_refine_nothing() -> None:
    assert response_facts("hubspot.deals.write", _body({"id": "x"})).link is None
    assert request_facts("mcp.some_tool", _body({"channel": "x"})).destination is None
