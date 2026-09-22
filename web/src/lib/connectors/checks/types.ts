import type { IconFunctionComponent } from "@opal/types";

/**
 * Where a check stands. The first three are finished; the last two are
 * still to come.
 */
export type CheckStatus =
  | "failed"
  | "completed"
  | "skipped"
  | "running"
  | "expected";

export interface ConnectorCheck {
  id: string;
  /** What the check verifies, e.g. "Check connector scopes". */
  name: string;
  status: CheckStatus;
  /** One line on the outcome or the current state. */
  detail?: string;
  /** A required check that fails blocks the connector. */
  required?: boolean;
  /** Shown as a marker after the detail, with this text as its tooltip. */
  warning?: string;
  /** Replaces the status icon, e.g. an hourglass for a check that waits on
   * the user rather than on the system. */
  icon?: IconFunctionComponent;
}
