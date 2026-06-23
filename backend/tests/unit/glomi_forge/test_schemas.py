from onyx.glomi_forge.schemas.events import parse_builder_event
from onyx.glomi_forge.schemas.events import PreviewReady
from onyx.glomi_forge.schemas.forge_spec import ForgeSpec
from onyx.glomi_forge.schemas.output_manifest import OutputManifest


def test_build_spec_minimal_roundtrip() -> None:
    spec = ForgeSpec(title="发布页", goal="生成中文产品落地页")
    dumped = spec.model_dump_json()
    again = ForgeSpec.model_validate_json(dumped)
    assert again.title == "发布页"
    assert again.requirements == []


def test_builder_event_discriminated_parse() -> None:
    raw = {"type": "preview_ready", "at": "2026-06-22T00:00:00Z", "port": 3000}
    ev = parse_builder_event(raw)
    assert isinstance(ev, PreviewReady)
    assert ev.port == 3000


def test_output_manifest_roundtrip() -> None:
    manifest = OutputManifest(
        primary_artifact_path="/workspace/out",
        primary_artifact_type="landing_page",
    )
    assert (
        OutputManifest.model_validate_json(
            manifest.model_dump_json()
        ).primary_artifact_type
        == "landing_page"
    )
