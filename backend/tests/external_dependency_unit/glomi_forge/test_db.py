from onyx.db.enums import ForgeArtifactType
from onyx.db.enums import GlomiForgeStatus
from onyx.db.glomi_forge import append_build_event
from onyx.db.glomi_forge import create_glomi_forge_session
from onyx.db.glomi_forge import fetch_forge_events_after
from onyx.db.glomi_forge import get_glomi_forge_session
from onyx.db.glomi_forge import update_status
from onyx.glomi_forge.schemas.events import PreviewReady
from onyx.glomi_forge.schemas.forge_spec import ForgeSpec


def test_create_and_status(db_session) -> None:
    session = create_glomi_forge_session(
        db_session,
        user_id=None,
        artifact_type=ForgeArtifactType.LANDING_PAGE,
        template_id="landing_page",
        spec=ForgeSpec(title="t", goal="g"),
        title="t",
    )

    update_status(db_session, session.id, GlomiForgeStatus.BUILDING)

    again = get_glomi_forge_session(db_session, session.id)
    assert again is not None
    assert again.status == GlomiForgeStatus.BUILDING
    assert again.spec["title"] == "t"


def test_events_seq_monotonic(db_session) -> None:
    session = create_glomi_forge_session(
        db_session,
        user_id=None,
        artifact_type=ForgeArtifactType.LANDING_PAGE,
        template_id="landing_page",
        spec=ForgeSpec(title="t", goal="g"),
        title="t",
    )

    seq1 = append_build_event(db_session, session.id, PreviewReady(at="x", port=3000))
    seq2 = append_build_event(db_session, session.id, PreviewReady(at="y", port=3001))

    assert (seq1, seq2) == (1, 2)
    rows = fetch_forge_events_after(db_session, session.id, after_seq=1)
    assert len(rows) == 1
    assert rows[0][1].port == 3001
