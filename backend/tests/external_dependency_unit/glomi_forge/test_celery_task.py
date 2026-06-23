from onyx.background.celery.tasks.glomi_forge.tasks import _run
from onyx.db.enums import ForgeArtifactType
from onyx.db.enums import GlomiForgeStatus
from onyx.db.glomi_forge import create_glomi_forge_session
from onyx.db.glomi_forge import get_glomi_forge_session
from onyx.glomi_forge.schemas.events import BuilderFinished
from onyx.glomi_forge.schemas.events import BuilderStarted
from onyx.glomi_forge.schemas.forge_spec import ForgeSpec
from onyx.glomi_forge.testing.fakes import FakeBuilderAdapter
from onyx.glomi_forge.testing.fakes import FakeSandboxProvider


def test_run_drives_orchestrator(db_session) -> None:
    session = create_glomi_forge_session(
        db_session,
        user_id=None,
        artifact_type=ForgeArtifactType.LANDING_PAGE,
        template_id="landing_page",
        spec=ForgeSpec(title="t", goal="g"),
        title="t",
    )

    _run(
        session.id,
        db_session,
        FakeSandboxProvider(),
        FakeBuilderAdapter(
            [BuilderStarted(at="0"), BuilderFinished(at="1", success=True)]
        ),
    )

    again = get_glomi_forge_session(db_session, session.id)
    assert again is not None
    assert again.status == GlomiForgeStatus.COMPLETED
