from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, field_validator

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheckResult,
    ProposedPairingValidation,
)
from onyx.connectors.config_diff import ConfigFieldChange
from onyx.connectors.models import InputType
from onyx.connectors.planning_rule import PlanningData
from onyx.db.backfill_models import BackfillSpec
from onyx.db.enums import AccessType, ConnectorCredentialPairStatus


class PairState(BaseModel):
    """The parts of a cc-pair that an edit can propose. The connector config
    is the full config, not a patch."""

    source: DocumentSource
    input_type: InputType | None
    connector_specific_config: dict[str, Any]
    access_type: AccessType
    data_access_group_ids: list[int] = []
    credential_id: int
    # Connector.indexing_start is a naive UTC column.
    indexing_start: datetime | None = None
    name: str
    refresh_freq: int | None = None
    prune_freq: int | None = None

    @field_validator("data_access_group_ids")
    @classmethod
    def _sorted_unique_groups(cls, group_ids: list[int]) -> list[int]:
        return sorted(set(group_ids))

    @field_validator("indexing_start")
    @classmethod
    def _utc_indexing_start(cls, value: datetime | None) -> datetime | None:
        if value is None or value.tzinfo is not None:
            return value
        return value.replace(tzinfo=timezone.utc)


class ProposedPairState(PairState):
    """The state an admin proposes for an existing cc-pair."""


class CurrentPairState(PairState):
    cc_pair_id: int
    connector_id: int
    status: ConnectorCredentialPairStatus


class EditStepKind(str, Enum):
    # Access steps apply at once, also on a paused pair.
    ACCESS_GROUPS = "access_groups"
    ACCESS_TYPE = "access_type"
    ENTER_PERM_SYNC = "enter_perm_sync"
    LEAVE_PERM_SYNC = "leave_perm_sync"
    # Stops an attempt that runs with the old config or credential.
    RESTART_ATTEMPT = "restart_attempt"
    FULL_REINDEX_THEN_PRUNE = "full_reindex_then_prune"
    FULL_REINDEX = "full_reindex"
    SCOPED_BACKFILL = "scoped_backfill"
    WINDOW_BACKFILL = "window_backfill"
    PRUNE = "prune"


class EditStepReason(str, Enum):
    IDENTITY_CHANGED = "identity_changed"
    BEHAVIOR_CHANGED = "behavior_changed"
    SCOPE_WIDENED = "scope_widened"
    SCOPE_NARROWED = "scope_narrowed"
    # A planning rule found items (e.g. files) that were added or changed, or
    # whose documents are gone.
    ITEMS_ADDED_OR_CHANGED = "items_added_or_changed"
    ITEMS_REMOVED = "items_removed"
    OPAQUE_SCOPE_CHOICE = "opaque_scope_choice"
    INDEXING_START_EARLIER = "indexing_start_earlier"
    INDEXING_START_LATER = "indexing_start_later"
    CREDENTIAL_FULL_PATH = "credential_full_path"
    ACCESS_CHANGED = "access_changed"
    # The source gets document permissions only while it indexes.
    PERMISSIONS_FETCHED_DURING_INDEXING = "permissions_fetched_during_indexing"
    ATTEMPT_RUNNING = "attempt_running"
    # A backfill of an earlier edit waits or runs with a config built from the
    # old config. A full re-index covers it.
    SCOPED_BACKFILL_SUPERSEDED = "scoped_backfill_superseded"
    ADMIN_ADDED = "admin_added"


class EditStep(BaseModel):
    kind: EditStepKind
    # A required step keeps the pair correct or secure; the admin cannot drop
    # it. Other steps are freshness work.
    required: bool
    reasons: list[EditStepReason]
    # The config fields that caused the step.
    field_names: list[str] = []
    # Set only for SCOPED_BACKFILL and WINDOW_BACKFILL.
    backfill: BackfillSpec | None = None


class EditNoteKind(str, Enum):
    ATTEMPT_RESTARTED = "attempt_restarted"
    PAUSED = "paused"
    INVALID_CLEARED_BY_VALIDATION = "invalid_cleared_by_validation"
    INDEXING_START_LATER = "indexing_start_later"
    CREDENTIAL_SWAP_USUALLY_NEEDS_FULL_PATH = "credential_swap_usually_needs_full_path"
    ACCESS_AFTER_METADATA_SYNC = "access_after_metadata_sync"
    STALE_SYNCED_ACLS = "stale_synced_acls"
    CHECKS_STILL_RUNNING = "checks_still_running"
    # A check that did not finish in the validation failed in a dry run.
    UNFINISHED_CHECK_FAILED_IN_DRY_RUN = "unfinished_check_failed_in_dry_run"


class EditNoteSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"


class EditNote(BaseModel):
    kind: EditNoteKind
    severity: EditNoteSeverity
    message: str


class ReconciliationOption(str, Enum):
    """The admin's choice for a scope change whose direction is unknown."""

    PRUNE = "prune"
    FULL_REINDEX = "full_reindex"
    BOTH = "both"
    NOTHING = "nothing"


class CredentialPath(str, Enum):
    # Keep what is indexed; later runs use the new credential.
    KEEP_INDEXED = "keep_indexed"
    FULL_REINDEX_AND_PRUNE = "full_reindex_and_prune"


class ReconciliationChoice(BaseModel):
    """Opaque scope changes: the plan has no recommendation, so the admin must
    pick one of ``options``."""

    field_names: list[str]
    options: list[ReconciliationOption] = list(ReconciliationOption)


class CredentialChoice(BaseModel):
    default: CredentialPath = CredentialPath.KEEP_INDEXED
    options: list[CredentialPath] = list(CredentialPath)


class EditPlanInputs(BaseModel):
    """What the planner needs besides the two states, gathered by the caller."""

    supports_windowed_runs: bool
    # A prune lists only the documents from the indexing start.
    prune_honors_indexing_start: bool
    fetches_permissions_during_indexing: bool
    access_filter_enforced: bool
    attempt_running: bool
    # A backfill with a config override waits on the pair or runs.
    scoped_backfill_outstanding: bool = False
    indexed_document_count: int
    now: datetime
    # None when nothing that validation checks changed.
    validation: ProposedPairingValidation | None = None
    dry_run_results: list[CapabilityCheckResult] = []
    # What the source's planning rule reads besides the configs, if anything.
    rule_data: PlanningData | None = None


class EditPlan(BaseModel):
    field_changes: list[ConfigFieldChange]
    # Pair settings that change and need no propagation (name, frequencies).
    changed_settings: list[str]
    # Recommended steps, deduplicated and in apply order.
    steps: list[EditStep]
    reconciliation_choice: ReconciliationChoice | None = None
    credential_choice: CredentialChoice | None = None
    notes: list[EditNote]
    validation: ProposedPairingValidation | None = None
    # Results of the pair's dry runs for this proposed state, for the checks
    # that are too slow for the blocking validation.
    dry_run_results: list[CapabilityCheckResult]
    indexed_document_count: int

    @property
    def validation_blocks_apply(self) -> bool:
        return self.validation is not None and self.validation.blocks_pairing


class EditPlanChoices(BaseModel):
    """The admin's answers to a plan, given at apply."""

    # Required when the plan has a reconciliation choice.
    reconciliation: ReconciliationOption | None = None
    # None takes the plan's default.
    credential_path: CredentialPath | None = None
    added_steps: list[EditStepKind] = []
    dropped_steps: list[EditStepKind] = []


class StoredEditPlan(BaseModel):
    plan_id: UUID
    cc_pair_id: int
    user_id: UUID
    base_state_hash: str
    proposed: ProposedPairState
    plan: EditPlan
    created_at: datetime
