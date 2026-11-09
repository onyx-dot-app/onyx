import io
import json
import tarfile
import zipfile

from pydantic import JsonValue

CLAUDE = ".claude-plugin/marketplace.json"
CODEX = ".agents/plugins/marketplace.json"


def _md(name: str = "hello") -> bytes:
    return (
        f"---\nname: {name}\ndescription: A test skill\n---\nUse the script.\n".encode()
    )


def _catalog(**fields: JsonValue) -> bytes:
    plugin: dict[str, JsonValue] = {"name": "tools", "source": "./"}
    plugin.update(fields)
    return json.dumps(
        {"name": "test", "owner": {"name": "Test"}, "plugins": [plugin], "future": True}
    ).encode()


def _files(**fields: JsonValue) -> dict[str, bytes]:
    return {CLAUDE: _catalog(**fields), "skills/hello/SKILL.md": _md()}


def _archive(files: dict[str, bytes], kind: str = "zip", wrapper: str = "") -> bytes:
    out = io.BytesIO()
    if kind == "tar":
        with tarfile.open(fileobj=out, mode="w:gz") as archive:
            for path, data in files.items():
                info = tarfile.TarInfo(wrapper + path)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
    elif kind == "zip":
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path, data in files.items():
                archive.writestr(wrapper + path, data)
    else:
        raise ValueError(f"Unsupported archive format: {kind}")
    return out.getvalue()
