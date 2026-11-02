"""Run SDK seeding against real temporary session directories."""

import os
import subprocess
from pathlib import Path

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[7]
    / "onyx/server/features/build/sandbox/image/seed-opencode-dependencies.sh"
)


@pytest.fixture
def sdk_template(tmp_path: Path) -> Path:
    template = tmp_path / "template"
    dependencies = template / "node_modules" / "plugin"
    dependencies.mkdir(parents=True)
    (dependencies / "index.js").write_text("sdk")
    (template / "package.json").write_text('{"dependencies":{"plugin":"1.0.0"}}')
    (template / "package-lock.json").write_text("{}")
    return template


def _seed(session: Path, template: Path) -> None:
    subprocess.run(["sh", str(_SCRIPT), str(session), str(template)], check=True)


def test_fresh_seed_replay_and_session_isolation(
    tmp_path: Path, sdk_template: Path
) -> None:
    first = tmp_path / "first session"
    second = tmp_path / "second session"
    _seed(first, sdk_template)
    _seed(second, sdk_template)
    sdk_file = Path(".opencode/node_modules/plugin/index.js")
    assert (first / sdk_file).read_text() == "sdk"
    assert (first / ".opencode/package-lock.json").read_text() == "{}"
    (first / sdk_file).write_text("session change")
    _seed(first, sdk_template)
    assert (first / sdk_file).read_text() == "session change"
    assert (second / sdk_file).read_text() == "sdk"
    assert (sdk_template / "node_modules/plugin/index.js").read_text() == "sdk"


def test_existing_manifests_remain_intact(tmp_path: Path, sdk_template: Path) -> None:
    config = tmp_path / "session/.opencode"
    config.mkdir(parents=True)
    for name in ("package.json", "package-lock.json"):
        (config / name).write_text("session-owned")
    _seed(config.parent, sdk_template)
    for name in ("package.json", "package-lock.json"):
        assert (config / name).read_text() == "session-owned"
    assert (config / "node_modules/plugin/index.js").read_text() == "sdk"


def test_existing_dependencies_are_not_replaced(
    tmp_path: Path, sdk_template: Path
) -> None:
    config = tmp_path / "session/.opencode"
    (config / "node_modules").mkdir(parents=True)
    (config / "node_modules/custom").write_text("existing")
    _seed(config.parent, sdk_template)
    assert (config / "node_modules/custom").read_text() == "existing"
    assert not (config / "package.json").exists()


def test_missing_template_leaves_runtime_install_fallback(tmp_path: Path) -> None:
    session = tmp_path / "session"
    _seed(session, tmp_path / "missing-template")
    assert not session.exists()


def test_failed_copy_does_not_publish_partial_dependencies_and_retry_succeeds(
    tmp_path: Path, sdk_template: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands = tmp_path / "commands"
    commands.mkdir()
    copy = commands / "cp"
    copy.write_text(
        '#!/bin/sh\nmkdir -p "$3/node_modules/plugin"\n'
        'echo partial > "$3/node_modules/plugin/index.js"\nexit 1\n'
    )
    copy.chmod(0o755)
    session = tmp_path / "session"
    with monkeypatch.context() as patched:
        patched.setenv("PATH", f"{commands}{os.pathsep}{os.environ['PATH']}")
        with pytest.raises(subprocess.CalledProcessError):
            _seed(session, sdk_template)
    assert not (session / ".opencode/node_modules").exists()
    assert list((session / ".opencode").iterdir()) == []
    _seed(session, sdk_template)
    assert (session / ".opencode/node_modules/plugin/index.js").read_text() == "sdk"
