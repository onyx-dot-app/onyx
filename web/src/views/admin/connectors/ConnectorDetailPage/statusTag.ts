import type { IconFunctionComponent } from "@opal/types";
import type { TagColor } from "@opal/components";
import { IconLoader } from "@opal/loaders";
import {
  SvgAlertTriangle,
  SvgCheckCircle,
  SvgClock,
  SvgPauseCircle,
  SvgXOctagon,
} from "@opal/icons";
import {
  type CCPairRun,
  type CheckRunStatus,
  ConnectorCredentialPairStatus,
  type PruneRunStatus,
} from "@/lib/connectors/types";
import type { ValidStatuses } from "@/lib/types";

/** One pair or attempt state as its status tag shows it. */
export interface StatusTag {
  icon: IconFunctionComponent;
  color: TagColor;
  /** Key under `admin.status.badges`. */
  labelKey:
    | "deleting"
    | "paused"
    | "error"
    | "scheduled"
    | "initialIndexing"
    | "invalid"
    | "indexing"
    | "canceled"
    | "interrupted"
    | "indexed"
    | "failed"
    | "completedWithErrors"
    | "syncing"
    | "synced"
    | "pruning"
    | "pruned"
    | "checking"
    | "passed"
    | "failedToRun";
}

const TAGS = {
  deleting: { icon: SvgAlertTriangle, color: "red", labelKey: "deleting" },
  paused: { icon: SvgPauseCircle, color: "gray", labelKey: "paused" },
  error: { icon: SvgAlertTriangle, color: "red", labelKey: "error" },
  scheduled: { icon: SvgClock, color: "gray", labelKey: "scheduled" },
  initialIndexing: {
    icon: IconLoader,
    color: "blue",
    labelKey: "initialIndexing",
  },
  invalid: { icon: SvgXOctagon, color: "red", labelKey: "invalid" },
  indexing: { icon: IconLoader, color: "blue", labelKey: "indexing" },
  canceled: { icon: SvgClock, color: "gray", labelKey: "canceled" },
  // Resumes on its own, so it reads neutral rather than as indexed.
  interrupted: { icon: SvgClock, color: "gray", labelKey: "interrupted" },
  indexed: { icon: SvgCheckCircle, color: "green", labelKey: "indexed" },
  failed: { icon: SvgXOctagon, color: "red", labelKey: "failed" },
  completedWithErrors: {
    icon: SvgAlertTriangle,
    color: "amber",
    labelKey: "completedWithErrors",
  },
  syncing: { icon: IconLoader, color: "blue", labelKey: "syncing" },
  synced: { icon: SvgCheckCircle, color: "green", labelKey: "synced" },
  pruning: { icon: IconLoader, color: "blue", labelKey: "pruning" },
  pruned: { icon: SvgCheckCircle, color: "green", labelKey: "pruned" },
  checking: { icon: IconLoader, color: "blue", labelKey: "checking" },
  passed: { icon: SvgCheckCircle, color: "green", labelKey: "passed" },
  failedToRun: { icon: SvgXOctagon, color: "red", labelKey: "failedToRun" },
} satisfies Record<StatusTag["labelKey"], StatusTag>;

/** The tag for the pair's own state, else the latest attempt's. A live attempt outranks the sticky error. */
export function ccPairStatusTag(
  status: ConnectorCredentialPairStatus,
  inRepeatedErrorState: boolean,
  lastAttemptStatus: ValidStatuses | null | undefined
): StatusTag {
  if (status === ConnectorCredentialPairStatus.DELETING) return TAGS.deleting;
  if (status === ConnectorCredentialPairStatus.PAUSED) return TAGS.paused;
  if (inRepeatedErrorState && lastAttemptStatus !== "in_progress") {
    return TAGS.error;
  }
  if (status === ConnectorCredentialPairStatus.SCHEDULED) return TAGS.scheduled;
  if (status === ConnectorCredentialPairStatus.INITIAL_INDEXING) {
    return TAGS.initialIndexing;
  }
  if (status === ConnectorCredentialPairStatus.INVALID) return TAGS.invalid;
  switch (lastAttemptStatus) {
    case "in_progress":
      return TAGS.indexing;
    case "not_started":
      return TAGS.scheduled;
    case "canceled":
      return TAGS.canceled;
    case "interrupted":
      return TAGS.interrupted;
    default:
      return TAGS.indexed;
  }
}

function pruneStatusTag(status: PruneRunStatus): StatusTag {
  switch (status) {
    case "in_progress":
      return TAGS.pruning;
    case "success":
      return TAGS.pruned;
    case "failed":
      return TAGS.failed;
    case "canceled":
      return TAGS.canceled;
  }
}

function checkRunStatusTag(status: CheckRunStatus): StatusTag {
  switch (status) {
    case "running":
      return TAGS.checking;
    case "passed":
      return TAGS.passed;
    case "failed":
      return TAGS.failed;
    case "failed_to_run":
      return TAGS.failedToRun;
  }
}

/** The tag of one run in the pair's run list, whatever its kind. */
export function runStatusTag(run: CCPairRun): StatusTag {
  switch (run.kind) {
    case "indexing":
      return attemptStatusTag(run.attempt.status, false);
    case "doc_permission_sync":
    case "group_sync":
      return attemptStatusTag(run.attempt.status, true);
    case "pruning":
      return pruneStatusTag(run.attempt.status);
    case "checks":
      return checkRunStatusTag(run.attempt.status);
  }
}

/** One attempt's tag. A sync reads "Syncing" and "Synced" where indexing reads "Indexing" and "Indexed". */
export function attemptStatusTag(
  status: ValidStatuses | null,
  isSync: boolean
): StatusTag {
  switch (status) {
    case null:
    case "not_started":
      return TAGS.scheduled;
    case "in_progress":
      return isSync ? TAGS.syncing : TAGS.indexing;
    case "success":
      return isSync ? TAGS.synced : TAGS.indexed;
    case "completed_with_errors":
      return TAGS.completedWithErrors;
    case "failed":
      return TAGS.failed;
    case "interrupted":
      return TAGS.interrupted;
    case "canceled":
      return TAGS.canceled;
    case "invalid":
      return TAGS.invalid;
  }
}
