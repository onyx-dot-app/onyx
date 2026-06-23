import importlib.util
import pathlib

_spec = importlib.util.spec_from_file_location(
    "glomi_run_build",
    pathlib.Path("backend/onyx/glomi_forge/sandbox_image/run_forge.py"),
)
assert _spec is not None
assert _spec.loader is not None
run_build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_build)


def test_normalize_text_delta() -> None:
    out = run_build.normalize_pi_event(
        {
            "type": "message_update",
            "assistantMessageEvent": {"type": "text_delta", "delta": "hi"},
        }
    )

    assert out["type"] == "message_delta"
    assert out["text"] == "hi"


def test_normalize_agent_end_is_dropped() -> None:
    assert run_build.normalize_pi_event({"type": "agent_end", "messages": []}) is None


def test_normalize_unknown_dropped() -> None:
    assert run_build.normalize_pi_event({"type": "whatever"}) is None
