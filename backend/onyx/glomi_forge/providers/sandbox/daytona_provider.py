"""SandboxProvider backed by the Daytona SDK."""

from importlib import import_module
from types import SimpleNamespace
from typing import Any

from onyx.glomi_forge.configs import DAYTONA_API_KEY
from onyx.glomi_forge.configs import DAYTONA_API_URL
from onyx.glomi_forge.schemas.sandbox import CommandResult
from onyx.glomi_forge.schemas.sandbox import CreateSandboxInput
from onyx.glomi_forge.schemas.sandbox import CreateSandboxResult
from onyx.glomi_forge.schemas.sandbox import PreviewInfo
from onyx.glomi_forge.schemas.sandbox import SandboxFile


def _snapshot_params(input: CreateSandboxInput) -> Any:
    try:
        daytona = import_module("daytona")
    except ModuleNotFoundError:
        return SimpleNamespace(
            snapshot=input.snapshot,
            env_vars=input.env_vars or None,
            labels=input.labels or None,
        )

    return daytona.CreateSandboxFromSnapshotParams(
        snapshot=input.snapshot,
        env_vars=input.env_vars or None,
        labels=input.labels or None,
    )


class DaytonaSandboxProvider:
    def __init__(self, client: Any | None = None) -> None:
        if client is None:
            daytona = import_module("daytona")

            client = daytona.Daytona(
                daytona.DaytonaConfig(
                    api_key=DAYTONA_API_KEY,
                    api_url=DAYTONA_API_URL,
                )
            )
        self.client = client
        self._handles: dict[str, Any] = {}

    def create_sandbox(self, input: CreateSandboxInput) -> CreateSandboxResult:
        sandbox = self.client.create(_snapshot_params(input))
        self._handles[sandbox.id] = sandbox
        return CreateSandboxResult(sandbox_id=sandbox.id, status="started")

    def write_files(self, sandbox_id: str, files: list[SandboxFile]) -> None:
        sandbox = self._handle(sandbox_id)
        for file in files:
            sandbox.fs.upload_file(file.content.encode("utf-8"), file.path)

    def read_file(self, sandbox_id: str, path: str) -> str:
        data = self._handle(sandbox_id).fs.download_file(path)
        if isinstance(data, bytes):
            return data.decode("utf-8")
        return str(data)

    def run_command(
        self,
        sandbox_id: str,
        command: str,
        cwd: str | None = None,
    ) -> CommandResult:
        response = self._handle(sandbox_id).process.exec(command, cwd=cwd)
        return CommandResult(
            exit_code=response.exit_code,
            stdout=getattr(response, "result", "") or "",
        )

    def expose_preview(self, sandbox_id: str, port: int) -> PreviewInfo:
        sandbox = self._handle(sandbox_id)
        sandbox.public = True
        link = sandbox.get_preview_link(port)
        return PreviewInfo(
            url=link.url,
            port=port,
            token=getattr(link, "token", None),
        )

    def stop_sandbox(self, sandbox_id: str) -> None:
        self.client.stop(self._handle(sandbox_id))

    def delete_sandbox(self, sandbox_id: str) -> None:
        sandbox = self._handle(sandbox_id)
        self.client.delete(sandbox)
        self._handles.pop(sandbox_id, None)

    def _handle(self, sandbox_id: str) -> Any:
        return self._handles[sandbox_id]
