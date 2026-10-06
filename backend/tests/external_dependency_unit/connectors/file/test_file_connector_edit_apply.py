"""A file connector edit end to end: files staged for the edit, the plan from
the file planning rule, apply, and the beat. Apply claims the new files and
the backfill the beat creates indexes only them; a removed file is pruned. A
second zip in the same edit merges into the draft's metadata."""

from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.docprocessing.tasks import _kickoff_indexing_tasks
from onyx.connectors.capability_checks.models import ProposedPairingValidation
from onyx.connectors.edit_plan import apply as apply_module
from onyx.connectors.edit_plan import orchestration
from onyx.connectors.edit_plan.apply import apply_connector_edit
from onyx.connectors.edit_plan.models import (
    EditPlanChoices,
    EditStepKind,
    ProposedPairState,
)
from onyx.connectors.edit_plan.orchestration import plan_connector_edit
from onyx.connectors.edit_plan.state import fetch_current_pair_state
from onyx.connectors.file.connector import LocalFileConnector
from onyx.connectors.models import Document
from onyx.db.models import IndexAttempt, User
from onyx.db.search_settings import get_current_search_settings
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.redis.redis_pool import get_redis_client
from onyx.server.documents.file_connector_staging import stage_file_connector_upload
from shared_configs.contextvars import get_current_tenant_id
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user
from tests.external_dependency_unit.connectors.file.file_edit_helpers import (
    FilePair,
    read_json_file,
    staged_file_ids,
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
    monkeypatch.setattr(
        apply_module, "validate_and_record_pairing", MagicMock(return_value=True)
    )


@pytest.fixture
def admin(db_session: Session) -> Generator[User, None, None]:
    user = create_test_user(db_session, "file_edit_apply_admin", is_admin=True)
    yield user
    db_session.rollback()
    delete_test_user(db_session, user)
    db_session.commit()


@pytest.fixture
def attempt_cleanup(
    db_session: Session, file_pair: FilePair
) -> Generator[None, None, None]:
    yield
    db_session.rollback()
    db_session.execute(
        delete(IndexAttempt).where(
            IndexAttempt.connector_credential_pair_id == file_pair.pair.id
        )
    )
    db_session.commit()


def _proposed(
    db_session: Session, file_pair: FilePair, **config: Any
) -> ProposedPairState:
    current = fetch_current_pair_state(db_session, file_pair.pair.id)
    return ProposedPairState.model_validate(
        current.model_dump(exclude={"cc_pair_id", "connector_id", "status"})
        | {"connector_specific_config": current.connector_specific_config | config}
    )


@pytest.mark.usefixtures("attempt_cleanup")
def test_apply_indexes_only_the_claimed_files(
    db_session: Session, file_pair: FilePair, admin: User
) -> None:
    current_a, _ = file_pair.save_current_files(db_session, {"a.txt": _A, "b.txt": _B})
    staged = stage_file_connector_upload(
        db_session, file_pair.pair.id, [text_upload("c.txt", _C)]
    )
    [file_c] = staged.file_paths
    file_pair.file_ids.append(file_c)

    stored = plan_connector_edit(
        db_session,
        cc_pair_id=file_pair.pair.id,
        proposed=_proposed(
            db_session,
            file_pair,
            file_locations=[current_a, file_c],
            file_names=["a.txt", "c.txt"],
        ),
        user=admin,
    )
    assert [step.kind for step in stored.plan.steps] == [
        EditStepKind.SCOPED_BACKFILL,
        EditStepKind.PRUNE,
    ]

    apply_connector_edit(
        db_session, stored=stored, choices=EditPlanChoices(), user=admin
    )

    pair = file_pair.pair
    db_session.expire_all()
    assert file_c not in staged_file_ids(db_session, pair.id)
    assert pair.connector.connector_specific_config["file_locations"] == [
        current_a,
        file_c,
    ]
    assert pair.prune_requested_at is not None
    [pending] = pair.pending_backfills
    override = pending.backfill.connector_config_override
    assert override is not None
    assert override["file_locations"] == [file_c]

    # A file connector has no refresh_freq; the backfill still runs.
    _kickoff_indexing_tasks(
        celery_app=MagicMock(),
        db_session=db_session,
        search_settings=get_current_search_settings(db_session),
        cc_pair_ids=[pair.id],
        secondary_index_building=False,
        redis_client=get_redis_client(),
        lock_beat=MagicMock(),
        tenant_id=get_current_tenant_id(),
    )
    db_session.expire_all()
    [attempt] = db_session.scalars(
        select(IndexAttempt).where(IndexAttempt.connector_credential_pair_id == pair.id)
    ).all()
    assert attempt.is_backfill
    assert attempt.connector_config_override == override
    # The request stays until the attempt succeeds.
    [tracked] = pair.pending_backfills
    assert tracked.attempt_id == attempt.id

    # Docfetching builds the connector from the override.
    connector = LocalFileConnector(**override)
    connector.load_credentials({})
    documents = [
        doc
        for batch in connector.load_from_state()
        for doc in batch
        if isinstance(doc, Document)
    ]
    assert [doc.semantic_identifier for doc in documents] == ["c.txt"]


def test_second_zip_merges_into_the_draft_metadata(
    db_session: Session, file_pair: FilePair
) -> None:
    [current_a] = file_pair.save_current_files(
        db_session,
        {"a.txt": _A},
        zip_metadata={"a.txt": {"link": "https://example.com/a"}},
    )
    pair_id = file_pair.pair.id

    first = stage_file_connector_upload(
        db_session,
        pair_id,
        [zip_upload({"x.txt": b"x"}, [{"filename": "x.txt", "link": "x-link"}])],
    )
    assert first.zip_metadata_file_id is not None

    second = stage_file_connector_upload(
        db_session,
        pair_id,
        [zip_upload({"y.txt": b"y"}, [{"filename": "y.txt", "link": "y-link"}])],
        draft_zip_metadata_file_id=first.zip_metadata_file_id,
    )
    assert second.zip_metadata_file_id is not None
    merged = read_json_file(second.zip_metadata_file_id)
    assert set(merged) == {"a.txt", "x.txt", "y.txt"}

    # Without a zip, the draft's metadata stays the draft's.
    plain = stage_file_connector_upload(
        db_session,
        pair_id,
        [text_upload("z.txt", b"z")],
        draft_zip_metadata_file_id=second.zip_metadata_file_id,
    )
    assert plain.zip_metadata_file_id == second.zip_metadata_file_id

    # A file that is neither the pair's metadata nor staged for this edit.
    with pytest.raises(OnyxError) as exc:
        stage_file_connector_upload(
            db_session,
            pair_id,
            [text_upload("w.txt", b"w")],
            draft_zip_metadata_file_id=current_a,
        )
    assert exc.value.error_code == OnyxErrorCode.INVALID_INPUT
