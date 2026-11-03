"""Planning a file connector edit against stored and staged files: only new
or changed files are indexed, removed files are pruned, and a zip-metadata
change re-indexes only the files whose entries changed. A metadata file that
cannot be used fails planning."""

from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from onyx.connectors.edit_plan import orchestration
from onyx.connectors.edit_plan.models import (
    EditPlan,
    EditStepKind,
    ProposedPairState,
)
from onyx.connectors.edit_plan.orchestration import plan_connector_edit
from onyx.connectors.edit_plan.state import fetch_current_pair_state
from onyx.connectors.factory import ProposedPairingValidation
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.documents.connector import upload_files
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user
from tests.external_dependency_unit.connectors.file.file_edit_helpers import (
    FilePair,
    text_upload,
    zip_upload,
)

_A = b"alpha content"
_B = b"bravo content"
_C = b"charlie content"


@pytest.fixture(autouse=True)
def validation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        orchestration,
        "validate_proposed_pairing",
        MagicMock(return_value=ProposedPairingValidation()),
    )
    monkeypatch.setattr(
        orchestration, "get_cc_pair_dry_run_results", MagicMock(return_value=[])
    )


@pytest.fixture
def admin(db_session: Session) -> Generator[User, None, None]:
    user = create_test_user(db_session, "file_edit_plan_admin", is_admin=True)
    yield user
    db_session.rollback()
    delete_test_user(db_session, user)
    db_session.commit()


def _plan(
    db_session: Session, file_pair: FilePair, admin: User, **config: Any
) -> EditPlan:
    current = fetch_current_pair_state(db_session, file_pair.pair.id)
    proposed = ProposedPairState.model_validate(
        current.model_dump(exclude={"cc_pair_id", "connector_id", "status"})
        | {"connector_specific_config": current.connector_specific_config | config}
    )
    return plan_connector_edit(
        db_session, cc_pair_id=file_pair.pair.id, proposed=proposed, user=admin
    ).plan


def test_added_and_removed_files(
    db_session: Session, file_pair: FilePair, admin: User
) -> None:
    current_a, _ = file_pair.save_current_files(db_session, {"a.txt": _A, "b.txt": _B})
    staged = file_pair.stage(db_session, [text_upload("c.txt", _C)])

    plan = _plan(
        db_session,
        file_pair,
        admin,
        file_locations=[current_a, *staged.file_paths],
        file_names=["a.txt", "c.txt"],
    )

    assert [step.kind for step in plan.steps] == [
        EditStepKind.SCOPED_BACKFILL,
        EditStepKind.PRUNE,
    ]
    backfill = plan.steps[0].backfill
    assert backfill is not None
    assert backfill.connector_config_override is not None
    assert backfill.connector_config_override["file_locations"] == staged.file_paths


def test_metadata_change_reindexes_only_the_changed_files(
    db_session: Session, file_pair: FilePair, admin: User
) -> None:
    current_ids = file_pair.save_current_files(
        db_session,
        {"a.txt": _A, "b.txt": _B},
        zip_metadata={
            "a.txt": {"filename": "a.txt", "title": "A"},
            "b.txt": {"filename": "b.txt", "title": "B"},
        },
    )
    # The zip holds a.txt again (same bytes) with a new title.
    staged = file_pair.stage(
        db_session,
        [zip_upload({"a.txt": _A}, [{"filename": "a.txt", "title": "A2"}])],
    )
    assert staged.file_paths == current_ids[:1]

    plan = _plan(
        db_session,
        file_pair,
        admin,
        zip_metadata_file_id=staged.zip_metadata_file_id,
    )

    assert [step.kind for step in plan.steps] == [EditStepKind.SCOPED_BACKFILL]
    backfill = plan.steps[0].backfill
    assert backfill is not None
    assert backfill.connector_config_override is not None
    assert backfill.connector_config_override["file_locations"] == current_ids[:1]
    assert backfill.connector_config_override["zip_metadata_file_id"] == (
        staged.zip_metadata_file_id
    )


def test_added_file_must_be_staged_for_the_pair(
    db_session: Session, file_pair: FilePair, admin: User
) -> None:
    [current_a] = file_pair.save_current_files(db_session, {"a.txt": _A})
    unstaged = upload_files([text_upload("c.txt", _C)])
    file_pair.file_ids.extend(unstaged.file_paths)

    with pytest.raises(OnyxError) as exc:
        _plan(
            db_session,
            file_pair,
            admin,
            file_locations=[current_a, *unstaged.file_paths],
        )
    assert exc.value.error_code == OnyxErrorCode.INVALID_INPUT


def test_unusable_metadata_file_fails_planning(
    db_session: Session, file_pair: FilePair, admin: User
) -> None:
    file_pair.save_current_files(db_session, {"a.txt": _A})

    with pytest.raises(OnyxError) as exc:
        _plan(
            db_session,
            file_pair,
            admin,
            zip_metadata_file_id=file_pair.save_metadata_file(b"null"),
        )
    assert exc.value.error_code == OnyxErrorCode.INVALID_INPUT
