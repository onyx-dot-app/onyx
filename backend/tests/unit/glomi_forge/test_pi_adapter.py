from onyx.glomi_forge.providers.builder.pi_builder_adapter import PiBuilderAdapter
from onyx.glomi_forge.schemas.builder import StartBuildInput
from onyx.glomi_forge.schemas.sandbox import CommandResult


class _StubProvider:
    def __init__(self, payloads: list[str]) -> None:
        self._payloads = list(payloads)
        self.commands: list[tuple[str, str, str | None]] = []
        self.reads: list[tuple[str, str]] = []

    def run_command(
        self,
        sandbox_id: str,
        command: str,
        cwd: str | None = None,
    ) -> CommandResult:
        self.commands.append((sandbox_id, command, cwd))
        return CommandResult(exit_code=0, stdout="")

    def read_file(self, sandbox_id: str, path: str) -> str:
        self.reads.append((sandbox_id, path))
        if len(self._payloads) > 1:
            return self._payloads.pop(0)
        return self._payloads[0]


def test_subscribe_yields_until_finished() -> None:
    line1 = '{"type":"builder_started","at":"0"}\n'
    line2 = line1 + '{"type":"preview_ready","at":"1","port":3000}\n'
    line3 = line2 + '{"type":"builder_finished","at":"2","success":true}\n'
    provider = _StubProvider([line1, line2, line3, line3])
    adapter = PiBuilderAdapter(provider, poll_interval=0)

    start = adapter.start_build(
        StartBuildInput(build_session_id="b", sandbox_id="sbx")
    )

    assert any("run_forge.py" in command for _, command, _ in provider.commands)
    types = [event.type for event in adapter.subscribe(start.builder_session_id)]
    assert types[0] == "builder_started"
    assert types[-1] == "builder_finished"
