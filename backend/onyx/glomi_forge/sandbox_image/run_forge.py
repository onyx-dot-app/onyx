"""In-sandbox launcher that normalizes Pi output into ForgeEvent JSONL."""

import json
import os
import subprocess
import sys
from datetime import datetime
from datetime import timezone
from typing import Any

EVENTS = "/workspace/logs/events.jsonl"
SRC = "/workspace/src"
OUT_MANIFEST = "/workspace/out/output_manifest.json"
PREVIEW_PORT = 3000


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def emit(event: dict[str, Any]) -> None:
    os.makedirs("/workspace/logs", exist_ok=True)
    with open(EVENTS, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def normalize_pi_event(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Map one raw Pi JSON event to our ForgeEvent dict, or drop it."""
    event_type = raw.get("type")
    if event_type == "agent_start":
        return {"type": "builder_started", "at": _now()}
    if event_type == "message_update":
        message_event = raw.get("assistantMessageEvent") or {}
        if not isinstance(message_event, dict):
            return None
        if message_event.get("type") == "text_delta":
            return {
                "type": "message_delta",
                "at": _now(),
                "text": message_event.get("delta", ""),
            }
    return None


def _read_json(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"expected object JSON at {path}")
    return data


def _read_text(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _build_prompt() -> str:
    task = _read_json("/workspace/input/task.json")
    agents = _read_text("/workspace/context/AGENTS.md")
    contract = _read_text("/workspace/context/output_contract.md")
    return (
        f"{agents}\n\n"
        f"# Task\n{json.dumps(task, ensure_ascii=False, indent=2)}\n\n"
        f"{contract}\n\n"
        f"构建落地页，完成后确保 port {PREVIEW_PORT} 可预览。"
    )


def _write_manifest() -> None:
    os.makedirs("/workspace/out", exist_ok=True)
    manifest = {
        "artifact_version": 1,
        "primary_artifact_path": SRC,
        "primary_artifact_type": "landing_page",
        "preview_entry": {"url": "", "port": PREVIEW_PORT, "route": "/"},
        "files": [{"path": f"{SRC}/app/page.tsx", "kind": "source"}],
        "notes": [],
    }
    with open(OUT_MANIFEST, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False)


def _run_pi() -> int:
    proc = subprocess.Popen(
        ["pi", "-p", _build_prompt(), "--mode", "json"],
        cwd=SRC,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert proc.stdout is not None
    for raw_line in proc.stdout:
        line = raw_line.strip()
        if not line:
            continue
        try:
            raw_event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(raw_event, dict):
            continue
        normalized = normalize_pi_event(raw_event)
        if normalized is not None:
            emit(normalized)
    return proc.wait()


def main() -> int:
    try:
        emit({"type": "builder_started", "at": _now()})
        subprocess.run(
            [sys.executable, "/opt/glomi/write_models_json.py"],
            check=True,
        )
        code = _run_pi()
        if code != 0:
            emit(
                {
                    "type": "builder_failed",
                    "at": _now(),
                    "error": f"pi exited {code}",
                }
            )
            return code

        subprocess.Popen(
            [
                "bun",
                "run",
                "dev",
                "--",
                "-H",
                "0.0.0.0",  # noqa: S104 - sandbox preview must bind externally.
                "-p",
                str(PREVIEW_PORT),
            ],
            cwd=SRC,
        )
        _write_manifest()
        emit({"type": "preview_ready", "at": _now(), "port": PREVIEW_PORT, "route": "/"})
        emit({"type": "artifact_ready", "at": _now(), "manifest_path": OUT_MANIFEST})
        emit({"type": "builder_finished", "at": _now(), "success": True})
        return 0
    except Exception as e:
        emit({"type": "builder_failed", "at": _now(), "error": str(e)})
        return 1


if __name__ == "__main__":
    sys.exit(main())
