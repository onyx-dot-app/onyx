from onyx.db.enums import ForgeArtifactType
from onyx.db.enums import GlomiForgeStatus
from onyx.db.glomi_forge import create_glomi_forge_session
from onyx.db.glomi_forge import fetch_forge_events_after
from onyx.db.glomi_forge import get_glomi_forge_session
from onyx.glomi_forge.schemas.events import ArtifactReady
from onyx.glomi_forge.schemas.events import BuilderFailed
from onyx.glomi_forge.schemas.events import BuilderFinished
from onyx.glomi_forge.schemas.events import BuilderStarted
from onyx.glomi_forge.schemas.events import PreviewReady
from onyx.glomi_forge.schemas.forge_spec import ForgeSpec
from onyx.glomi_forge.services.forge_orchestrator import ForgeOrchestrator
from onyx.glomi_forge.services.template_service import TemplateService
from onyx.glomi_forge.testing.fakes import FakeBuilderAdapter
from onyx.glomi_forge.testing.fakes import FakeSandboxProvider

MANIFEST = (
    '{"artifact_version":1,"primary_artifact_path":"/workspace/src",'
    '"primary_artifact_type":"landing_page","files":[],"notes":[]}'
)


def _make_session(db_session):
    return create_glomi_forge_session(
        db_session,
        user_id=None,
        artifact_type=ForgeArtifactType.LANDING_PAGE,
        template_id="landing_page",
        spec=ForgeSpec(title="t", goal="g"),
        title="t",
    )


def test_happy_path_reaches_completed(db_session) -> None:
    session = _make_session(db_session)
    events = [
        BuilderStarted(at="0"),
        PreviewReady(at="1", port=3000),
        ArtifactReady(at="2", manifest_path="/workspace/out/output_manifest.json"),
        BuilderFinished(at="3", success=True),
    ]
    provider = FakeSandboxProvider(
        preview_url="http://preview.local",
        read_payload=MANIFEST,
    )
    adapter = FakeBuilderAdapter(scripted_events=events)

    ForgeOrchestrator(db_session, provider, adapter, TemplateService()).run(session.id)

    again = get_glomi_forge_session(db_session, session.id)
    assert again is not None
    assert again.status == GlomiForgeStatus.COMPLETED
    assert again.preview_url == "http://preview.local"
    assert again.sandbox_id is not None
    assert again.latest_output["primary_artifact_type"] == "landing_page"
    assert len(fetch_forge_events_after(db_session, session.id, after_seq=0)) >= 4


def test_builder_failure_marks_failed_and_cleans_up(db_session) -> None:
    session = _make_session(db_session)
    events = [BuilderStarted(at="0"), BuilderFailed(at="1", error="boom")]
    provider = FakeSandboxProvider()
    adapter = FakeBuilderAdapter(scripted_events=events)

    ForgeOrchestrator(db_session, provider, adapter, TemplateService()).run(session.id)

    again = get_glomi_forge_session(db_session, session.id)
    assert again is not None
    assert again.status == GlomiForgeStatus.FAILED
    assert again.last_error["message"] == "boom"
    assert provider.deleted
