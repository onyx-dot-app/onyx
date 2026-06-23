"""BuilderAdapter for the in-sandbox Pi launcher."""

import json
import time
from collections.abc import Iterator

from onyx.glomi_forge.interfaces.sandbox_provider import SandboxProvider
from onyx.glomi_forge.schemas.builder import StartBuildInput
from onyx.glomi_forge.schemas.builder import StartBuildResult
from onyx.glomi_forge.schemas.events import ForgeEvent
from onyx.glomi_forge.schemas.events import parse_builder_event

_EVENTS_PATH = "/workspace/logs/events.jsonl"
_TERMINAL_EVENTS = {"builder_finished", "builder_failed"}


class PiBuilderAdapter:
    def __init__(
        self,
        provider: SandboxProvider,
        poll_interval: float = 1.0,
        max_polls: int = 1800,
    ) -> None:
        self.provider = provider
        self.poll_interval = poll_interval
        self.max_polls = max_polls

    def start_build(self, input: StartBuildInput) -> StartBuildResult:
        self.provider.run_command(
            input.sandbox_id,
            "mkdir -p /workspace/logs && "
            "nohup python3 /opt/glomi/run_forge.py "
            "> /workspace/logs/launcher.log 2>&1 &",
        )
        return StartBuildResult(builder_session_id=input.sandbox_id)

    def subscribe(self, builder_session_id: str) -> Iterator[ForgeEvent]:
        seen = 0
        for _ in range(self.max_polls):
            try:
                content = self.provider.read_file(builder_session_id, _EVENTS_PATH)
            except Exception:
                content = ""
            lines = [line for line in content.splitlines() if line.strip()]
            for raw_line in lines[seen:]:
                event = parse_builder_event(json.loads(raw_line))
                yield event
                if event.type in _TERMINAL_EVENTS:
                    return
            seen = len(lines)
            if self.poll_interval:
                time.sleep(self.poll_interval)

    def stop(self, builder_session_id: str) -> None:
        self.provider.run_command(builder_session_id, "pkill -f run_forge.py || true")
