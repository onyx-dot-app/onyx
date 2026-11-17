import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

GATE = Path(__file__).resolve().parents[1] / "hooks" / "verification_trailer.py"


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo, check=check, capture_output=True, text=True
    )


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("ONYX_VERIFICATION_SESSION", raising=False)
    monkeypatch.delenv("CODEX_SESSION_ID", raising=False)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.name", "Onyx test")
    git(tmp_path, "config", "user.email", "verify@example.com")
    hooks = tmp_path / ".git" / "hooks"
    git(tmp_path, "config", "core.hooksPath", str(hooks))
    for stage in ("commit-msg", "post-commit"):
        hook = hooks / stage
        command = shlex.join([sys.executable, str(GATE)])
        hook.write_text(f'#!/bin/sh\nexec {command} "$@"\n', encoding="utf-8")
        hook.chmod(0o755)
    return tmp_path


def commit(repo: Path, *trailers: str) -> subprocess.CompletedProcess[str]:
    args = [arg for value in trailers for arg in ("--trailer", f"Verified-by: {value}")]
    return git(
        repo, "commit", "--allow-empty", "-m", "test: exercise gate", *args, check=False
    )


def test_observe_logs_the_unstamped_commit(repo: Path) -> None:
    assert commit(repo).returncode == 0
    sha = git(repo, "rev-parse", "HEAD").stdout.strip()
    assert commit(repo, "e2e").returncode == 0
    log = (repo / ".git" / "onyx-verification.log").read_text(encoding="utf-8")
    assert log.split()[1:] == [sha, "missing", "or", "invalid", "Verified-by"]


def test_off_ignores_unstamped_commits(repo: Path) -> None:
    git(repo, "config", "onyx.verificationMode", "off")
    assert commit(repo).returncode == 0
    assert not (repo / ".git" / "onyx-verification.log").exists()


@pytest.mark.parametrize(
    "trailers", [(), ("unknown",), ("none",), ("none ( )",), ("unit", "e2e")]
)
def test_enforce_rejects_missing_or_invalid_stamps(
    repo: Path, trailers: tuple[str, ...]
) -> None:
    git(repo, "config", "onyx.verificationMode", "enforce")
    result = commit(repo, *trailers)
    assert result.returncode != 0
    assert "Add Verified-by:" in result.stderr
    assert not (repo / ".git" / "onyx-verification.log").exists()
    assert commit(repo, "none (No app setup)").returncode == 0
    assert commit(repo, "integration").returncode == 0


def test_enforce_allows_third_attempt_per_session(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    git(repo, "config", "onyx.verificationMode", "enforce")
    monkeypatch.setenv("ONYX_VERIFICATION_SESSION", "first")
    assert commit(repo).returncode != 0
    assert commit(repo).returncode != 0

    monkeypatch.setenv("ONYX_VERIFICATION_SESSION", "second")
    assert commit(repo).returncode != 0
    monkeypatch.setenv("ONYX_VERIFICATION_SESSION", "first")
    assert commit(repo).returncode == 0
    assert commit(repo).returncode != 0

    assert commit(repo, "unit").returncode == 0
    assert commit(repo).returncode != 0
    assert commit(repo).returncode != 0
    assert commit(repo).returncode == 0


def test_enforce_accepts_stamp_above_verbose_diff(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    git(repo, "config", "onyx.verificationMode", "enforce")
    (repo / "change").write_text("a change\n", encoding="utf-8")
    git(repo, "add", "change")
    editor = repo / "editor"
    editor.write_text(
        "#!/bin/sh\n"
        "printf 'test: exercise editor\n\nVerified-by: unit\n\n' > message\n"
        'cat "$1" >> message\n'
        'mv message "$1"\n',
        encoding="utf-8",
    )
    editor.chmod(0o755)
    monkeypatch.setenv("GIT_EDITOR", str(editor))
    result = git(repo, "commit", "--verbose", check=False)
    assert result.returncode == 0, result.stderr
