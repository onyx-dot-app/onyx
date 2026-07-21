"""Guards the IDP_PROFILE_CLAIM_MAP env parsing: every ignored shape must warn,
since a silently dropped map is invisible misconfiguration."""

import logging

from onyx.configs.app_configs import parse_idp_claim_map


def test_valid_map_parses() -> None:
    raw = '{"department": ["dept", "division"], "country": ["c"]}'
    assert parse_idp_claim_map(raw) == {
        "department": ["dept", "division"],
        "country": ["c"],
    }


def test_unset_returns_empty() -> None:
    assert parse_idp_claim_map(None) == {}
    assert parse_idp_claim_map("") == {}


def test_invalid_json_warns_and_ignores(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        assert parse_idp_claim_map("{not json") == {}
    assert "not valid JSON" in caplog.text


def test_non_object_json_warns_and_ignores(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        assert parse_idp_claim_map('["department"]') == {}
    assert "must be a JSON object" in caplog.text


def test_non_list_entry_warns_and_is_dropped(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        parsed = parse_idp_claim_map('{"department": "dept", "country": ["c"]}')
    assert parsed == {"country": ["c"]}
    assert "must map to a list" in caplog.text
