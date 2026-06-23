from types import SimpleNamespace
from unittest.mock import MagicMock

from onyx.glomi_forge.providers.sandbox.daytona_provider import DaytonaSandboxProvider
from onyx.glomi_forge.schemas.sandbox import CreateSandboxInput
from onyx.glomi_forge.schemas.sandbox import SandboxFile


def _fake_sandbox():
    sandbox = SimpleNamespace()
    sandbox.id = "sbx-1"
    sandbox.public = False
    sandbox.fs = MagicMock()
    sandbox.process = MagicMock()
    sandbox.process.exec.return_value = SimpleNamespace(exit_code=0, result="ok")
    sandbox.get_preview_link = MagicMock(
        return_value=SimpleNamespace(url="http://p", token="t")
    )
    return sandbox


def test_create_and_preview_and_delete() -> None:
    client = MagicMock()
    sandbox = _fake_sandbox()
    client.create.return_value = sandbox
    provider = DaytonaSandboxProvider(client=client)

    result = provider.create_sandbox(
        CreateSandboxInput(session_id="s", snapshot="glomi-landing-page")
    )
    assert result.sandbox_id == "sbx-1"

    provider.write_files(
        "sbx-1",
        [SandboxFile(path="/workspace/a.txt", content="x")],
    )
    sandbox.fs.upload_file.assert_called_once()

    preview = provider.expose_preview("sbx-1", 3000)
    assert preview.url == "http://p"
    assert sandbox.public is True

    provider.delete_sandbox("sbx-1")
    client.delete.assert_called_once_with(sandbox)
