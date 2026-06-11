"""Lock down that long shell scripts can't leak through ExecError messages.

Setup scripts (``setup_session_workspace``, ``restore_snapshot``) embed
the LLM API key inline via ``printf '%s' '<opencode.json>' > opencode.json``.
If exec fails, the script ends up in ``ExecError`` — which gets logged.
This test pins the redaction behavior so a refactor can't accidentally
revert it.
"""

from __future__ import annotations

from onyx.server.features.build.sandbox.docker.internal.exec_helpers import (
    _command_summary,
)


def test_command_summary_redacts_long_shell_script() -> None:
    sk_secret = "sk-VERY-SECRET-OPENAI-API-KEY-DO-NOT-LEAK"
    long_script = (
        "set -e\n"
        f"printf '%s' '{{\"apiKey\": \"{sk_secret}\"}}' > opencode.json\n"
        + "# more setup lines\n"
        * 30
    )
    cmd = ["/bin/sh", "-c", long_script]
    out = _command_summary(cmd)
    assert sk_secret not in out, "API key leaked through _command_summary"
    assert "<shell script:" in out, "expected length tag in redacted output"


def test_command_summary_preserves_short_argv() -> None:
    """Short args like ``['tar', '-czf', '-']`` should be readable in errors."""
    cmd = ["tar", "-czf", "-"]
    out = _command_summary(cmd)
    assert "tar" in out
    assert "-czf" in out


def test_command_summary_handles_string_form() -> None:
    short = "ls /workspace"
    long = "echo " + "x" * 300
    assert _command_summary(short).startswith("'") or "ls" in _command_summary(short)
    assert "<shell script:" in _command_summary(long)
