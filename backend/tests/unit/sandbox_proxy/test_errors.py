"""Contract tests for the sandbox-facing 403 builder.

Pins the response shape every code must satisfy without asserting the exact
prose (which is free to be reworded). The completeness check guarantees a new
code can't ship without a message.
"""

import json

import pytest

from onyx.sandbox_proxy.errors import http_403
from onyx.sandbox_proxy.errors import SandboxProxyError


@pytest.mark.parametrize("code", list(SandboxProxyError))
def test_http_403_carries_code_and_prose(code: SandboxProxyError) -> None:
    response = http_403(code)

    assert response.status_code == 403
    assert response.headers["content-type"] == "application/json"

    assert response.content is not None
    body = json.loads(response.content)

    # Stable code for tooling, prose for the agent.
    assert body["error"] == code.value
    message = body["message"]
    assert isinstance(message, str)
    # Prose, not a restated code: non-trivial length and not the bare slug.
    assert len(message) > 40
    assert message != code.value


def test_every_code_has_a_message() -> None:
    # Mirrors the import-time guard so the contract is asserted in CI even if the
    # module is already imported (and thus its guard already passed).
    for code in SandboxProxyError:
        assert code.message
