"""In-memory test doubles for Glomi Forge providers and adapters."""

from collections.abc import Iterator

from onyx.glomi_forge.schemas.builder import StartBuildInput
from onyx.glomi_forge.schemas.builder import StartBuildResult
from onyx.glomi_forge.schemas.events import ForgeEvent
from onyx.glomi_forge.schemas.sandbox import CommandResult
from onyx.glomi_forge.schemas.sandbox import CreateSandboxInput
from onyx.glomi_forge.schemas.sandbox import CreateSandboxResult
from onyx.glomi_forge.schemas.sandbox import PreviewInfo
from onyx.glomi_forge.schemas.sandbox import SandboxFile


class FakeSandboxProvider:
    def __init__(
        self,
        preview_url: str = "http://preview.local",
        read_payload: str = "{}",
    ) -> None:
        self.preview_url = preview_url
        self.read_payload = read_payload
        self.created: list[CreateSandboxInput] = []
        self.written: dict[str, list[SandboxFile]] = {}
        self.reads: list[tuple[str, str]] = []
        self.commands: list[tuple[str, str, str | None]] = []
        self.previews: list[tuple[str, int]] = []
        self.stopped_sandboxes: list[str] = []
        self.deleted: list[str] = []
        self._counter = 0

    def create_sandbox(self, input: CreateSandboxInput) -> CreateSandboxResult:
        self._counter += 1
        self.created.append(input)
        return CreateSandboxResult(
            sandbox_id=f"fake-{self._counter}",
            status="started",
        )

    def write_files(self, sandbox_id: str, files: list[SandboxFile]) -> None:
        self.written.setdefault(sandbox_id, []).extend(files)

    def read_file(self, sandbox_id: str, path: str) -> str:
        self.reads.append((sandbox_id, path))
        return self.read_payload

    def run_command(
        self,
        sandbox_id: str,
        command: str,
        cwd: str | None = None,
    ) -> CommandResult:
        self.commands.append((sandbox_id, command, cwd))
        return CommandResult(exit_code=0, stdout="")

    def expose_preview(self, sandbox_id: str, port: int) -> PreviewInfo:
        self.previews.append((sandbox_id, port))
        return PreviewInfo(url=self.preview_url, port=port)

    def stop_sandbox(self, sandbox_id: str) -> None:
        self.stopped_sandboxes.append(sandbox_id)

    def delete_sandbox(self, sandbox_id: str) -> None:
        self.deleted.append(sandbox_id)


class FakeBuilderAdapter:
    def __init__(self, scripted_events: list[ForgeEvent]) -> None:
        self.scripted_events = scripted_events
        self.started: list[StartBuildInput] = []
        self.subscribed: list[str] = []
        self.stopped_sessions: list[str] = []
        self.stopped = False

    def start_build(self, input: StartBuildInput) -> StartBuildResult:
        self.started.append(input)
        return StartBuildResult(builder_session_id=f"builder-{input.sandbox_id}")

    def subscribe(self, builder_session_id: str) -> Iterator[ForgeEvent]:
        self.subscribed.append(builder_session_id)
        yield from self.scripted_events

    def stop(self, builder_session_id: str) -> None:
        self.stopped_sessions.append(builder_session_id)
        self.stopped = True
