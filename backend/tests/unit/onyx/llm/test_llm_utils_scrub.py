"""Unit tests for `onyx.llm.utils` helpers, focused on the secret-scrubbing
behavior that protects `/admin/llm/test` (and `validate_existing_genai_api_key`)
from echoing API keys back through error messages.
"""

from collections.abc import Iterable
from typing import Any

from onyx.llm.interfaces import LLM
from onyx.llm.interfaces import LLMConfig
from onyx.llm.utils import collect_llm_credential_values
from onyx.llm.utils import is_sensitive_custom_config_key
from onyx.llm.utils import scrub_sensitive_values
from onyx.llm.utils import (
    test_llm as run_test_llm,
)  # aliased to avoid pytest collection

_SECRET_KEY = "sk-anthropic-supersecret-DO-NOT-LEAK-1234567890"
_SECRET_VERTEX_BLOB = (
    '{"private_key":"-----BEGIN PRIVATE KEY-----abc-----END PRIVATE KEY-----"}'
)


class _StubLLM(LLM):
    """Minimal LLM that lets us drive `test_llm` through both success and
    failure paths without going anywhere near LiteLLM."""

    def __init__(
        self,
        config: LLMConfig,
        *,
        raise_on_invoke: Exception | None = None,
    ) -> None:
        self._config = config
        self._raise_on_invoke = raise_on_invoke
        self.invoke_calls = 0

    @property
    def config(self) -> LLMConfig:
        return self._config

    def invoke(self, *_: Any, **__: Any) -> Any:  # noqa: D401, ANN401
        self.invoke_calls += 1
        if self._raise_on_invoke is not None:
            raise self._raise_on_invoke
        return None


def _make_config(
    *,
    api_key: str | None = _SECRET_KEY,
    custom_config: dict[str, str] | None = None,
) -> LLMConfig:
    return LLMConfig(
        model_provider="anthropic",
        model_name="claude-3-5-sonnet",
        temperature=0.0,
        api_key=api_key,
        api_base=None,
        api_version=None,
        deployment_name=None,
        custom_config=custom_config,
        max_input_tokens=200_000,
    )


# ---------------------------------------------------------------------------
# is_sensitive_custom_config_key
# ---------------------------------------------------------------------------


def test_is_sensitive_custom_config_key_matches_known_fragments() -> None:
    assert is_sensitive_custom_config_key("api_key")
    assert is_sensitive_custom_config_key("API_KEY")
    assert is_sensitive_custom_config_key("aws_secret_access_key")
    assert is_sensitive_custom_config_key("vertex_credentials")
    assert is_sensitive_custom_config_key("my_password")
    assert is_sensitive_custom_config_key("auth_token")


def test_is_sensitive_custom_config_key_rejects_benign_keys() -> None:
    assert not is_sensitive_custom_config_key("api_base")
    assert not is_sensitive_custom_config_key("region")
    assert not is_sensitive_custom_config_key("model")
    assert not is_sensitive_custom_config_key("deployment_name")


# ---------------------------------------------------------------------------
# scrub_sensitive_values
# ---------------------------------------------------------------------------


def test_scrub_replaces_literal_secrets() -> None:
    msg = f"AuthError: provided key {_SECRET_KEY} was rejected"
    assert _SECRET_KEY in msg

    scrubbed = scrub_sensitive_values(msg, [_SECRET_KEY])

    assert _SECRET_KEY not in scrubbed
    assert "[REDACTED]" in scrubbed


def test_scrub_ignores_empty_and_short_secrets() -> None:
    # short / empty / None secrets must be ignored so we don't accidentally
    # eat common substrings like "ok" or "id".
    msg = "id=abc okOk Token=foo"

    scrubbed = scrub_sensitive_values(msg, [None, "", "ok", "id"])

    assert scrubbed == msg


def test_scrub_replaces_multiple_occurrences_of_same_secret() -> None:
    msg = f"sent {_SECRET_KEY} then retried with {_SECRET_KEY}"

    scrubbed = scrub_sensitive_values(msg, [_SECRET_KEY])

    assert _SECRET_KEY not in scrubbed
    assert scrubbed.count("[REDACTED]") == 2


def test_scrub_handles_empty_message() -> None:
    assert scrub_sensitive_values("", [_SECRET_KEY]) == ""


def test_scrub_leaves_message_untouched_when_no_secrets_present() -> None:
    msg = "Authentication failed: Please check your API key and credentials."

    assert scrub_sensitive_values(msg, [_SECRET_KEY]) == msg


def test_scrub_accepts_iterable_secrets() -> None:
    secrets: Iterable[str | None] = iter([_SECRET_KEY])
    msg = f"upstream said: {_SECRET_KEY}"

    scrubbed = scrub_sensitive_values(msg, secrets)

    assert _SECRET_KEY not in scrubbed


# ---------------------------------------------------------------------------
# collect_llm_credential_values
# ---------------------------------------------------------------------------


def test_collect_llm_credential_values_includes_api_key_and_sensitive_config() -> None:
    config = _make_config(
        custom_config={
            "api_base": "https://api.example.com",
            "vertex_credentials": _SECRET_VERTEX_BLOB,
            "aws_secret_access_key": "AWSSECRET123456",
        },
    )
    llm = _StubLLM(config)

    values = collect_llm_credential_values(llm)

    assert _SECRET_KEY in values
    assert _SECRET_VERTEX_BLOB in values
    assert "AWSSECRET123456" in values
    assert "https://api.example.com" not in values


def test_collect_llm_credential_values_returns_empty_for_none() -> None:
    assert collect_llm_credential_values(None) == []


def test_collect_llm_credential_values_skips_missing_api_key() -> None:
    config = _make_config(api_key=None, custom_config={"region": "us-east-1"})
    llm = _StubLLM(config)

    assert collect_llm_credential_values(llm) == []


# ---------------------------------------------------------------------------
# test_llm — end-to-end sanitization
# ---------------------------------------------------------------------------


def test_run_test_llm_returns_none_on_success() -> None:
    llm = _StubLLM(_make_config())

    assert run_test_llm(llm) is None
    assert llm.invoke_calls == 1


def test_run_test_llm_redacts_api_key_from_unknown_exception() -> None:
    # An unknown exception subclass falls into the `fallback_to_error_msg=False`
    # branch of `litellm_exception_to_error_msg`, which already returns a
    # generic message. The key thing we verify here is that even if the raw
    # exception text contained the API key, it does NOT make it into the
    # returned message.
    boom = RuntimeError(
        f"upstream blew up. Authorization: Bearer {_SECRET_KEY}; "
        f"raw key={_SECRET_KEY}"
    )
    llm = _StubLLM(_make_config(), raise_on_invoke=boom)

    error_msg = run_test_llm(llm)

    assert error_msg is not None
    assert _SECRET_KEY not in error_msg
    # `test_llm` retries up to twice on failure.
    assert llm.invoke_calls == 2


def test_run_test_llm_redacts_litellm_authentication_error_payload() -> None:
    # Use the real LiteLLM AuthenticationError so we exercise the
    # litellm_exception_to_error_msg mapping path.
    from litellm.exceptions import AuthenticationError

    err = AuthenticationError(
        message=(
            f"AnthropicException - 401: invalid api key. "
            f"Authorization: Bearer {_SECRET_KEY}"
        ),
        llm_provider="anthropic",
        model="claude-3-5-sonnet",
    )
    llm = _StubLLM(_make_config(), raise_on_invoke=err)

    error_msg = run_test_llm(llm)

    assert error_msg is not None
    assert _SECRET_KEY not in error_msg
    # Friendly fallback message should still surface.
    assert "Authentication failed" in error_msg


def test_run_test_llm_redacts_custom_config_secret_from_error() -> None:
    config = _make_config(
        api_key=None,
        custom_config={"aws_secret_access_key": "AWSSECRET-LEAKED-9999"},
    )
    boom = RuntimeError("BotoError: signing failed using key AWSSECRET-LEAKED-9999")
    llm = _StubLLM(config, raise_on_invoke=boom)

    error_msg = run_test_llm(llm)

    assert error_msg is not None
    assert "AWSSECRET-LEAKED-9999" not in error_msg
