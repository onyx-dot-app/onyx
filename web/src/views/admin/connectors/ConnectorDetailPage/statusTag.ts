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
import { ConnectorCredentialPairStatus } from "@/lib/connectors/types";
import type { ValidStatuses } from "@/lib/types";

/** One pair state as the status tag shows it. */
export interface CCPairStatusTag {
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
    | "indexed";
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
} satisfies Record<CCPairStatusTag["labelKey"], CCPairStatusTag>;

/** The tag for the pair's own state, else the latest attempt's. A live attempt outranks the sticky error. */
export function ccPairStatusTag(
  status: ConnectorCredentialPairStatus,
  inRepeatedErrorState: boolean,
  lastAttemptStatus: ValidStatuses | null | undefined
): CCPairStatusTag {
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
