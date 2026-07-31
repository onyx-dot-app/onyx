"""Replay-safety contract of the generated session-workspace scripts."""

import shlex
from uuid import uuid4

from onyx.server.features.build.sandbox.docker.docker_sandbox_manager import (
    build_sandbox_labels,
)
from onyx.server.features.build.sandbox.labels import LABEL_PROVISIONING_ATTEMPT
from onyx.server.features.build.sandbox.nextjs_dev import build_nextjs_start_script
from onyx.server.features.build.sandbox.session_workspace import (
    SETUP_IN_PROGRESS_MARKER,
    build_session_workspace_setup_script,
    build_workspace_exists_check_script,
)

_SESSION_PATH = "/workspace/sessions/00000000-0000-0000-0000-000000000000"


def _setup_script(nextjs_port: int | None = 3010) -> str:
    return build_session_workspace_setup_script(
        session_path=_SESSION_PATH,
        agents_md='# Agent\'s "instructions"',
        session_opencode_config_json='{"model": "x"}',
        nextjs_port=nextjs_port,
    )


class TestWorkspaceExistsCheck:
    def test_reports_missing_while_setup_in_progress(self) -> None:
        # A partial directory (marker present) must never be mistaken for a
        # ready workspace; a legacy directory (outputs, no marker) reads as
        # complete.
        script = build_workspace_exists_check_script(_SESSION_PATH)
        assert f'[ -d "{_SESSION_PATH}/outputs" ]' in script
        assert f'[ ! -f "{_SESSION_PATH}/{SETUP_IN_PROGRESS_MARKER}" ]' in script
        assert "WORKSPACE_FOUND" in script
        assert "WORKSPACE_MISSING" in script


class TestSetupScriptReplaySafety:
    def test_marker_brackets_the_setup(self) -> None:
        script = _setup_script()
        touch_index = script.index(f"touch {_SESSION_PATH}/{SETUP_IN_PROGRESS_MARKER}")
        remove_index = script.index(f"rm -f {_SESSION_PATH}/{SETUP_IN_PROGRESS_MARKER}")
        outputs_index = script.index("Copying outputs template")
        assert touch_index < outputs_index < remove_index

    def test_materialization_serialized_with_session_flock(self) -> None:
        script = _setup_script()
        assert f"8>{_SESSION_PATH}.setup.lock" in script
        # The flock must open before any workspace mutation.
        assert script.index("flock -x 8") < script.index("mkdir -p")

    def test_dev_server_starts_outside_the_setup_lock(self) -> None:
        # A backgrounded dev server inside the flock subshell would inherit
        # fd 8 and hold the setup lock for its entire lifetime, deadlocking
        # every later repair/restore. It must start after the lock releases.
        script = _setup_script()
        lock_close = script.index(f"8>{_SESSION_PATH}.setup.lock")
        assert script.index("bun run dev") > lock_close

    def test_agents_md_is_shell_quoted(self) -> None:
        # Content with quotes must round-trip through printf without breaking
        # out of the script.
        script = _setup_script()
        assert shlex.quote('# Agent\'s "instructions"') in script
        assert f"> {_SESSION_PATH}/AGENTS.md" in script

    def test_headless_omits_nextjs_start(self) -> None:
        script = _setup_script(nextjs_port=None)
        assert "bun run dev" not in script


class TestNextjsStartReplaySafety:
    def test_reuses_live_server_instead_of_spawning_duplicate(self) -> None:
        script = build_nextjs_start_script(_SESSION_PATH, 3010)
        pid_guard = script.index(f"[ -f {_SESSION_PATH}/nextjs.pid ]")
        spawn = script.index("nohup bun run dev")
        assert pid_guard < spawn
        assert "kill -0" in script

    def test_pid_guard_verifies_process_identity(self) -> None:
        # A recycled PID belonging to an unrelated process must not read as
        # "server already running" — the guard checks the process cwd too.
        script = build_nextjs_start_script(_SESSION_PATH, 3010)
        assert (
            f'"$(readlink /proc/$NEXTJS_PID/cwd 2>/dev/null)"'
            f' = "{_SESSION_PATH}/outputs/web"' in script
        )

    def test_check_and_spawn_is_serialized_and_server_drops_lock_fd(self) -> None:
        # Two replays past the materialization lock (e.g. a timed-out setup
        # still running beside its retry) must not both spawn; and the
        # backgrounded server must close the lock fd or it would hold the
        # lock forever.
        script = build_nextjs_start_script(_SESSION_PATH, 3010)
        assert f"9>{_SESSION_PATH}.nextjs.lock" in script
        assert script.index("flock -x 9") < script.index("nohup bun run dev")
        assert "2>&1 9>&- &" in script


class TestDockerSandboxLabels:
    def test_generation_label_stamped_when_provided(self) -> None:
        labels = build_sandbox_labels(
            uuid4(), "tenant", None, provisioning_attempt_number=7
        )
        assert labels[LABEL_PROVISIONING_ATTEMPT] == "7"

    def test_generation_label_omitted_for_generation_free_resources(self) -> None:
        labels = build_sandbox_labels(uuid4(), "tenant", None)
        assert LABEL_PROVISIONING_ATTEMPT not in labels
