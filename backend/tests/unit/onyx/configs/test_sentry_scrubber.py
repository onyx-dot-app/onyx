"""Guards the Sentry credential scrubber: a provider API key nested in a
captured `headers` dict (e.g. litellm's outbound request, where the key lives
under the hyphenated `x-api-key`) must be redacted, while non-sensitive
debugging fields are preserved."""

from onyx.configs.sentry import build_event_scrubber


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

    out = _frame_vars(event)
    # nested credential under a non-sensitive parent key is gone
    assert out["headers"]["x-api-key"] != secret
    # non-sensitive context is retained for debugging
    assert out["headers"]["content-type"] == "application/json"
    assert out["model"] == "claude-sonnet-4-6"


def test_scrubber_redacts_nested_authorization_header() -> None:
    secret = "Bearer placeholder-token-value-1234567890"
    event = _frame_event({"headers": {"authorization": secret}})

    build_event_scrubber().scrub_event(event)

    assert _frame_vars(event)["headers"]["authorization"] != secret
