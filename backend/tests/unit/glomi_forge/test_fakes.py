from onyx.glomi_forge.schemas.builder import StartBuildInput
from onyx.glomi_forge.schemas.events import BuilderFinished
from onyx.glomi_forge.schemas.events import PreviewReady
from onyx.glomi_forge.schemas.sandbox import CreateSandboxInput
from onyx.glomi_forge.testing.fakes import FakeBuilderAdapter
from onyx.glomi_forge.testing.fakes import FakeSandboxProvider


def test_fake_provider_create_and_preview() -> None:
    provider = FakeSandboxProvider(preview_url="http://preview.local")
    result = provider.create_sandbox(
        CreateSandboxInput(session_id="s", snapshot="snap")
    )

    assert result.sandbox_id.startswith("fake-")
    assert (
        provider.expose_preview(result.sandbox_id, 3000).url
        == "http://preview.local"
    )


def test_fake_adapter_scripts_events() -> None:
    events = [
        PreviewReady(at="x", port=3000),
        BuilderFinished(at="y", success=True),
    ]
    adapter = FakeBuilderAdapter(scripted_events=events)

    start = adapter.start_build(
        StartBuildInput(build_session_id="b", sandbox_id="sb")
    )
    got = list(adapter.subscribe(start.builder_session_id))

    assert [event.type for event in got] == ["preview_ready", "builder_finished"]
