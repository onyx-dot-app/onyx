import os
import sys
from pathlib import Path
from queue import Queue
from typing import Any

import pytest

from tests.external_dependency_unit.oauth_provider import test_native_clients as harness


def test_codex_replies_coalesced_with_notifications_are_not_lost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable: Path = tmp_path / "codex"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\n"
        "for line in sys.stdin:\n"
        "    request = json.loads(line)\n"
        "    notification = {'method': 'status/changed', 'params': {}}\n"
        "    reply = {'id': request['id'], 'result': {'tools': ['search_indexed_documents']}}\n"
        "    sys.stdout.write(json.dumps(notification) + '\\n' + json.dumps(reply) + '\\n')\n"
        "    sys.stdout.flush()\n"
    )
    executable.chmod(0o700)
    monkeypatch.setattr(harness, "_CLI_TIMEOUT_SECONDS", 2)

    reply: dict[str, Any] = harness._codex_discover_mcp_tools(
        str(executable), [], env=dict(os.environ), server_name="fixture"
    )

    assert reply == {"id": 2, "result": {"tools": ["search_indexed_documents"]}}


def test_codex_eof_without_reply_fails() -> None:
    lines: Queue[str | None] = Queue()
    lines.put(None)
    with pytest.raises(AssertionError, match="did not answer request 1"):
        harness._read_codex_app_server_response(lines, 1)


def test_codex_error_reply_fails() -> None:
    lines: Queue[str | None] = Queue()
    lines.put('{"id": 1, "error": {"message": "rejected"}}')
    with pytest.raises(AssertionError, match="request 1 failed"):
        harness._read_codex_app_server_response(lines, 1)
