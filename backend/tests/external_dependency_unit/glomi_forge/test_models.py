from onyx.db.enums import ForgeArtifactType
from onyx.db.enums import GlomiForgeStatus
from onyx.db.models import GlomiForgeEvent
from onyx.db.models import GlomiForgeSession


def test_enums_present() -> None:
    assert GlomiForgeStatus.QUEUED.value == "queued"
    assert ForgeArtifactType.LANDING_PAGE.value == "landing_page"


def test_tables_have_expected_columns() -> None:
    cols = set(GlomiForgeSession.__table__.columns.keys())
    assert {
        "id",
        "user_id",
        "artifact_type",
        "status",
        "spec",
        "sandbox_id",
        "preview_url",
        "latest_output",
        "last_error",
    }.issubset(cols)

    event_cols = set(GlomiForgeEvent.__table__.columns.keys())
    assert {"id", "session_id", "seq", "packet_json"}.issubset(event_cols)
