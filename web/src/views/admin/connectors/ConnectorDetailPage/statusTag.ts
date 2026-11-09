import type { IconFunctionComponent } from "@opal/types";
import type { StatusColor } from "@opal/types";
import { IconLoader } from "@opal/loaders";
import {
  SvgAlertTriangle,
  SvgCheckCircle,
  SvgClock,
  SvgPause,
  SvgXCircle,
  SvgXOctagon,
} from "@opal/icons";
import {
  type CCPairRun,
  type CCPairRunKind,
  type CheckRunStatus,
  ConnectorCredentialPairStatus,
  type IndexingConnectorStatus,
  type PruneRunStatus,
} from "@/lib/connectors/types";
import type { ValidStatuses } from "@/lib/types";

/** One pair or attempt state as its status tag shows it. */
export interface StatusTag {
  icon: IconFunctionComponent;
  color: StatusColor;
  /** Key under `admin.status.badges`. */
  labelKey:
    | "deleting"
    | "paused"
    | "scheduled"
    | "initialIndexing"
    | "invalid"
    | "indexing"
    | "canceled"
    | "interrupted"
    | "indexed"
    | "backfilling"
    | "backfilled"
    | "failed"
    | "syncing"
    | "synced"
    | "pruning"
    | "pruned"
    | "checking"
    | "passed"
    | "failedToRun";
}

const TAGS = {
  deleting: { icon: SvgAlertTriangle, color: "error", labelKey: "deleting" },
  paused: { icon: SvgPause, color: "pending", labelKey: "paused" },
  scheduled: { icon: SvgClock, color: "queued", labelKey: "scheduled" },
  initialIndexing: {
    icon: IconLoader,
    color: "info",
    labelKey: "initialIndexing",
  },
  invalid: { icon: SvgXOctagon, color: "error", labelKey: "invalid" },
  indexing: { icon: IconLoader, color: "info", labelKey: "indexing" },
  canceled: { icon: SvgXCircle, color: "default", labelKey: "canceled" },
  // Resumes on its own, so it reads neutral rather than as indexed.
  interrupted: { icon: SvgXCircle, color: "default", labelKey: "interrupted" },
  indexed: { icon: SvgCheckCircle, color: "success", labelKey: "indexed" },
  backfilling: { icon: IconLoader, color: "info", labelKey: "backfilling" },
  backfilled: {
    icon: SvgCheckCircle,
    color: "success",
    labelKey: "backfilled",
  },
  failed: { icon: SvgXOctagon, color: "error", labelKey: "failed" },
  syncing: { icon: IconLoader, color: "info", labelKey: "syncing" },
  synced: { icon: SvgCheckCircle, color: "success", labelKey: "synced" },
  pruning: { icon: IconLoader, color: "info", labelKey: "pruning" },
  pruned: { icon: SvgCheckCircle, color: "success", labelKey: "pruned" },
  checking: { icon: IconLoader, color: "info", labelKey: "checking" },
  passed: { icon: SvgCheckCircle, color: "success", labelKey: "passed" },
  failedToRun: { icon: SvgXOctagon, color: "error", labelKey: "failedToRun" },
} satisfies Record<StatusTag["labelKey"], StatusTag>;

/** The warning look of an open error or warning count, on rows, run lines and the activity panel. */
export const ERROR_COUNT_TAG = {
  icon: SvgAlertTriangle,
  color: "warning",
} as const satisfies Pick<StatusTag, "icon" | "color">;

/** The tag for the pair's own state, else the latest attempt's. A live attempt outranks repeated failures. */
export function ccPairStatusTag(
  status: ConnectorCredentialPairStatus,
  inRepeatedErrorState: boolean,
  lastAttemptStatus: ValidStatuses | null | undefined
): StatusTag {
  if (status === ConnectorCredentialPairStatus.DELETING) return TAGS.deleting;
  if (status === ConnectorCredentialPairStatus.PAUSED) return TAGS.paused;
  // Repeated failures read "Failed", the same tag as the pair's row on the status page.
  if (inRepeatedErrorState && lastAttemptStatus !== "in_progress") {
    return TAGS.failed;
  }
  if (status === ConnectorCredentialPairStatus.INVALID) return TAGS.invalid;
  // A pair stays scheduled or initial indexing after its first run fails, and the status page reads it failed.
  if (lastAttemptStatus === "failed") return TAGS.failed;
  if (status === ConnectorCredentialPairStatus.SCHEDULED) return TAGS.scheduled;
  if (status === ConnectorCredentialPairStatus.INITIAL_INDEXING) {
    return TAGS.initialIndexing;
  }
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
      return attemptStatusTag(
        run.attempt.status,
        run.attempt.is_backfill ? "backfill" : "indexing"
      );
    case "doc_permission_sync":
    case "group_sync":
      return attemptStatusTag(run.attempt.status, "sync");
    case "pruning":
      return pruneStatusTag(run.attempt.status);
    case "checks":
      return checkRunStatusTag(run.attempt.status);
  }
}

/** A status page bucket's tag, as its row and its header count show it. */
export function bucketStatusTag(status: IndexingConnectorStatus): StatusTag {
  return TAGS[status];
}

/** The tag for a row of the status page: its bucket, unless the pair's own state or a stopped latest run says more. */
export function connectorRowStatusTag(
  ccPairStatus: ConnectorCredentialPairStatus,
  status: IndexingConnectorStatus,
  lastAttemptStatus: ValidStatuses | null | undefined
): StatusTag {
  if (ccPairStatus === ConnectorCredentialPairStatus.INVALID) {
    return TAGS.invalid;
  }
  if (
    ccPairStatus === ConnectorCredentialPairStatus.INITIAL_INDEXING &&
    status === "indexing"
  ) {
    return TAGS.initialIndexing;
  }
  if (status === "scheduled" && lastAttemptStatus === "canceled") {
    return TAGS.canceled;
  }
  if (status === "scheduled" && lastAttemptStatus === "interrupted") {
    return TAGS.interrupted;
  }
  return bucketStatusTag(status);
}

/** What an attempt does, which names its live and finished tags. */
export type AttemptWork = "indexing" | "backfill" | "sync";

const LIVE_TAGS = {
  indexing: TAGS.indexing,
  backfill: TAGS.backfilling,
  sync: TAGS.syncing,
} satisfies Record<AttemptWork, StatusTag>;

const DONE_TAGS = {
  indexing: TAGS.indexed,
  backfill: TAGS.backfilled,
  sync: TAGS.synced,
} satisfies Record<AttemptWork, StatusTag>;

/** One attempt's tag. A sync reads "Syncing" and "Synced" and a backfill "Backfilling" and "Backfilled" where indexing reads "Indexing" and "Indexed". */
export function attemptStatusTag(
  status: ValidStatuses | null,
  work: AttemptWork
): StatusTag {
  switch (status) {
    case null:
    case "not_started":
      return TAGS.scheduled;
    case "in_progress":
      return LIVE_TAGS[work];
    case "success":
    // Shares the success tag: the warning count beside it carries the document errors.
    case "completed_with_errors":
      return DONE_TAGS[work];
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

/** An index run that retries a pair's failed documents. */
export function isRetryRun(run: CCPairRun): boolean {
  return run.kind === "indexing" && run.is_retry === true;
}

/** Key under `admin.connector.runs.kinds`. Backfills and retries read apart from the pair's regular indexing. */
export function runKindLabelKey(
  run: CCPairRun
): CCPairRunKind | "backfill" | "retry" {
  if (run.kind !== "indexing") return run.kind;
  if (isRetryRun(run)) return "retry";
  return run.attempt.is_backfill ? "backfill" : run.kind;
}
