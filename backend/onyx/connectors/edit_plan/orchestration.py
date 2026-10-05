"""Gathers the planner's inputs for a proposed edit of a cc-pair, computes the
plan and stores it. Writes nothing except the plan store, and the credential
that the validation's connector construction can refresh and store."""

from datetime import datetime, timezone
from uuid import uuid4

import pydantic
from sqlalchemy.orm import Session

from onyx.access.access import source_should_fetch_permissions_during_indexing
from onyx.access.cc_pair_access import get_cc_pair_access_mode
from onyx.connectors.capability_checks.creation import get_cc_pair_dry_run_results
from onyx.connectors.capability_checks.models import ProposedPairingValidation
from onyx.connectors.config_diff import load_source_rule_data
from onyx.connectors.edit_plan.models import (
    CurrentPairState,
    EditPlanInputs,
    ProposedPairState,
    StoredEditPlan,
)
from onyx.connectors.edit_plan.planner import (
    compute_edit_plan,
    ensure_edit_is_plannable,
)
from onyx.connectors.edit_plan.state import fetch_current_pair_state
from onyx.connectors.edit_plan.store import compute_base_state_hash, save_edit_plan
from onyx.connectors.factory import (
    source_supports_windowed_runs,
    validate_connector_config,
    validate_proposed_pairing,
)
from onyx.connectors.pairing_access import validate_pairing_access
from onyx.connectors.registry import CONNECTOR_CLASS_MAP
from onyx.context.search.models import CCPairAccessMode
from onyx.db.connector_edit_requests import has_restartable_attempt
from onyx.db.credentials import fetch_credential_by_id
from onyx.db.document import get_document_counts_for_cc_pairs
from onyx.db.models import Credential, User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.documents.models import ConnectorCredentialPairIdentifier


def _fetch_proposed_credential(
    db_session: Session, current: CurrentPairState, proposed: ProposedPairState
) -> Credential:
    credential = fetch_credential_by_id(proposed.credential_id, db_session)
    if credential is None:
        raise OnyxError(
            OnyxErrorCode.CREDENTIAL_NOT_FOUND,
            f"Credential {proposed.credential_id} does not exist.",
        )
    if credential.source != current.source:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Credential {credential.id} is not a {current.source.value} credential.",
        )
    return credential


def _validate_proposed_state(
    db_session: Session,
    current: CurrentPairState,
    proposed: ProposedPairState,
    credential: Credential,
) -> ProposedPairingValidation | None:
    """The blocking validation, run only when something it checks changed."""
    if (
        proposed.connector_specific_config == current.connector_specific_config
        and proposed.credential_id == current.credential_id
        and proposed.access_type == current.access_type
    ):
        return None
    return validate_proposed_pairing(
        db_session,
        connector_id=current.connector_id,
        cc_pair_id=current.cc_pair_id,
        source=current.source,
        input_type=current.input_type,
        connector_specific_config=proposed.connector_specific_config,
        credential=credential,
        access_type=proposed.access_type,
    )


def _indexed_document_count(db_session: Session, current: CurrentPairState) -> int:
    counts = get_document_counts_for_cc_pairs(
        db_session,
        [
            ConnectorCredentialPairIdentifier(
                connector_id=current.connector_id,
                credential_id=current.credential_id,
            )
        ],
    )
    return next((count for _, _, count in counts), 0)


def plan_connector_edit(
    db_session: Session,
    *,
    cc_pair_id: int,
    proposed: ProposedPairState,
    user: User,
) -> StoredEditPlan:
    """Computes and stores the plan for moving the pair to ``proposed``.

    Runs the access gates and the blocking validation (about 3 s) on the
    proposed state, and reads the pair's cached dry-run results for the
    slower checks. Like any connector construction, the validation can store
    a credential that the connector refreshed. The caller authorizes the user
    for the pair and the proposed credential.

    Raises:
        OnyxError: The pair or credential does not exist, the edit cannot be
            planned (see ``ensure_edit_is_plannable``), the config does not
            match the source's config model, the source's planning rule
            rejects its data (e.g. a file that was not staged for the edit),
            or the access gates reject the proposed access.
    """
    current = fetch_current_pair_state(db_session, cc_pair_id)
    ensure_edit_is_plannable(current, proposed)
    rule_data = None
    if proposed.connector_specific_config != current.connector_specific_config:
        try:
            validate_connector_config(
                current.source, proposed.connector_specific_config
            )
        except pydantic.ValidationError as e:
            raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(e)) from e
        rule_data = load_source_rule_data(
            db_session,
            current.source,
            cc_pair_id,
            current.connector_specific_config,
            proposed.connector_specific_config,
        )
    if (
        proposed.access_type != current.access_type
        or proposed.data_access_group_ids != current.data_access_group_ids
    ):
        validate_pairing_access(
            db_session,
            user=user,
            source=current.source,
            access_type=proposed.access_type,
            data_access_group_ids=proposed.data_access_group_ids,
        )

    credential = _fetch_proposed_credential(db_session, current, proposed)
    validation = _validate_proposed_state(db_session, current, proposed, credential)
    dry_run_results = (
        get_cc_pair_dry_run_results(
            cc_pair_id=cc_pair_id,
            credential=credential,
            source=current.source,
            access_type=proposed.access_type,
            connector_specific_config=proposed.connector_specific_config,
        )
        if current.source in CONNECTOR_CLASS_MAP
        else []
    )
    inputs = EditPlanInputs(
        supports_windowed_runs=source_supports_windowed_runs(current.source),
        fetches_permissions_during_indexing=(
            source_should_fetch_permissions_during_indexing(current.source)
        ),
        access_filter_enforced=(
            get_cc_pair_access_mode(db_session) == CCPairAccessMode.ENFORCE
        ),
        attempt_running=has_restartable_attempt(db_session, cc_pair_id),
        indexed_document_count=_indexed_document_count(db_session, current),
        now=datetime.now(timezone.utc),
        validation=validation,
        dry_run_results=dry_run_results,
        rule_data=rule_data,
    )
    stored = StoredEditPlan(
        plan_id=uuid4(),
        cc_pair_id=cc_pair_id,
        user_id=user.id,
        base_state_hash=compute_base_state_hash(current),
        proposed=proposed,
        plan=compute_edit_plan(current, proposed, inputs),
        created_at=inputs.now,
    )
    save_edit_plan(stored)
    return stored
