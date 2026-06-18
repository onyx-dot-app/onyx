"""Guards the Sentry credential hardening:

1. ``build_event_scrubber()`` redacts a provider API key nested in a captured
   ``headers`` dict (e.g. litellm's outbound request, where the key lives under
   the hyphenated ``x-api-key``) while preserving non-sensitive fields.
2. ``init_sentry()`` actually wires the credential-safe kwargs into
   ``sentry_sdk.init`` so a future refactor can't silently drop them.
"""

from unittest.mock import patch

from sentry_sdk.scrubber import EventScrubber
from sentry_sdk.utils import AnnotatedValue

from onyx.configs.sentry import build_event_scrubber
from onyx.configs.sentry import init_sentry


def _frame_event(frame_vars: dict) -> dict:
    return {
        "exception": {"values": [{"stacktrace": {"frames": [{"vars": frame_vars}]}}]}
    }


def _frame_vars(event: dict) -> dict:
    return event["exception"]["values"][0]["stacktrace"]["frames"][0]["vars"]


def test_scrubber_redacts_nested_hyphenated_api_key_header() -> None:
    secret = "placeholder-credential-value-1234567890"
    event = _frame_event(
        {
            "headers": {"x-api-key": secret, "content-type": "application/json"},
            "model": "claude-sonnet-4-6",
        }
    )

    build_event_scrubber().scrub_event(event)

    headers = _frame_vars(event)["headers"]
    # key is preserved but swapped for sentry's redaction sentinel (not deleted,
    # not left as the secret) — pinning the type catches either regression cleanly
    assert "x-api-key" in headers
    assert isinstance(headers["x-api-key"], AnnotatedValue)
    # non-sensitive context is retained for debugging
    assert headers["content-type"] == "application/json"
    assert _frame_vars(event)["model"] == "claude-sonnet-4-6"


def test_scrubber_redacts_nested_authorization_header() -> None:
    secret = "Bearer placeholder-token-value-1234567890"
    event = _frame_event({"headers": {"authorization": secret}})

    build_event_scrubber().scrub_event(event)

    headers = _frame_vars(event)["headers"]
    assert "authorization" in headers
    assert isinstance(headers["authorization"], AnnotatedValue)


def test_init_sentry_wires_credential_safe_kwargs() -> None:
    with patch("sentry_sdk.init") as mock_init:
        init_sentry(traces_sample_rate=0.0)

    kwargs = mock_init.call_args.kwargs
    assert kwargs["include_local_variables"] is False
    assert kwargs["send_default_pii"] is False
    assert isinstance(kwargs["event_scrubber"], EventScrubber)


def test_build_event_scrubber_is_recursive_and_extends_denylist() -> None:
    scrubber = build_event_scrubber()
    # recursive is load-bearing: the stock scrubber only inspects top-level keys,
    # so a non-recursive one would never reach the nested headers.x-api-key
    assert scrubber.recursive is True
    assert "x-api-key" in scrubber.denylist
