import io
import json
import tarfile

from pydantic import JsonValue

CLAUDE = ".claude-plugin/marketplace.json"
CODEX = ".agents/plugins/marketplace.json"


def skill_md(name: str = "hello", description: str = "A test skill") -> bytes:
    return f"---\nname: {name}\ndescription: {description}\n---\nUse the script.\n".encode()


def catalog(*plugins: dict[str, JsonValue], **fields: JsonValue) -> bytes:
    return json.dumps(
        {"name": "test", "owner": {"name": "Test"}, "plugins": list(plugins)} | fields
    ).encode()


def plugin_json(name: str, **fields: JsonValue) -> bytes:
    return json.dumps({"name": name} | fields).encode()


def tar_archive(files: dict[str, bytes], wrapper: str = "acme-tools-abc123/") -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as archive:
        for path, data in files.items():
            info = tarfile.TarInfo(wrapper + path)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return out.getvalue()
