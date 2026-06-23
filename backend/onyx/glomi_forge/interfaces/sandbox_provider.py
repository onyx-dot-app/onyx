from typing import Protocol

from onyx.glomi_forge.schemas.sandbox import CommandResult
from onyx.glomi_forge.schemas.sandbox import CreateSandboxInput
from onyx.glomi_forge.schemas.sandbox import CreateSandboxResult
from onyx.glomi_forge.schemas.sandbox import PreviewInfo
from onyx.glomi_forge.schemas.sandbox import SandboxFile


class SandboxProvider(Protocol):
    def create_sandbox(self, input: CreateSandboxInput) -> CreateSandboxResult: ...

    def write_files(self, sandbox_id: str, files: list[SandboxFile]) -> None: ...

    def read_file(self, sandbox_id: str, path: str) -> str: ...

    def run_command(
        self,
        sandbox_id: str,
        command: str,
        cwd: str | None = None,
    ) -> CommandResult: ...

    def expose_preview(self, sandbox_id: str, port: int) -> PreviewInfo: ...

    def stop_sandbox(self, sandbox_id: str) -> None: ...

    def delete_sandbox(self, sandbox_id: str) -> None: ...
