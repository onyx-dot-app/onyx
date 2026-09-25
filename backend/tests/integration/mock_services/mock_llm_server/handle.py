from tests.integration.mock_services.mock_llm_server.models import (
    Lane,
    Matcher,
    RecordedRequest,
    Script,
    Step,
)
from tests.integration.mock_services.mock_llm_server.registry import ScriptRegistry
from tests.integration.mock_services.mock_llm_server.responders import Builtin


class ScriptHandle:
    """A test's view of one registered script."""

    def __init__(
        self,
        registry: ScriptRegistry,
        script_id: str,
        api_base: str,
        script: Script | None = None,
    ) -> None:
        self.registry = registry
        self.script_id = script_id
        self.api_base = api_base
        self.provider_id: int | None = None
        self.model_name: str | None = None
        registry.register(script_id, script)

    def add_lane(self, lane: Lane) -> Lane:
        self.registry.add_lane(self.script_id, lane)
        return lane

    def lane(self, name: str, *steps: Step, match: Matcher | None = None) -> Lane:
        return self.add_lane(
            Lane(name=name, match=match or Matcher(), steps=list(steps))
        )

    def extend_lane(self, name: str, *steps: Step) -> None:
        self.registry.extend_lane(self.script_id, name, list(steps))

    def set_builtin(self, name: Builtin | str, text: str) -> None:
        self.registry.set_builtin(self.script_id, str(name), text)

    def disable_builtin(self, name: Builtin | str) -> None:
        self.registry.disable_builtin(self.script_id, str(name))

    @property
    def requests(self) -> list[RecordedRequest]:
        return self.registry.requests(self.script_id)

    def lane_requests(self, name: str) -> list[RecordedRequest]:
        return [r for r in self.requests if r.lane == name]

    def builtin_requests(
        self, name: Builtin | str | None = None
    ) -> list[RecordedRequest]:
        return [
            r
            for r in self.requests
            if r.builtin is not None and (name is None or r.builtin == str(name))
        ]

    def unmatched_requests(self) -> list[RecordedRequest]:
        return [r for r in self.requests if r.error is not None]

    def pending_required_steps(self) -> list[str]:
        return self.registry.pending_required_steps(self.script_id)

    def verify(self) -> None:
        """Raise AssertionError for unmatched requests or unconsumed required
        steps."""
        problems = [
            f"request {request.index} ({request.error}): tools={request.tools} "
            f"tool_choice={request.tool_choice} "
            f"tool_results={request.tool_result_ids()} "
            f"prompt_start={request.prompt_text[:300]!r}"
            for request in self.unmatched_requests()
        ]
        problems.extend(f"unconsumed {step}" for step in self.pending_required_steps())
        if problems:
            raise AssertionError(
                "mock LLM script was not followed:\n  " + "\n  ".join(problems)
            )

    def close(self) -> None:
        self.registry.remove(self.script_id)
