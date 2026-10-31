import type {
  ConnectorChecksStatus,
  DraftCheckStateKind,
} from "@/lib/connectors/checks/types";

/** The ring's share for each colour, as `SvgProgressRing` takes them. */
export interface ChecksRing {
  success: number;
  error: number;
  warning: number;
  neutral: number;
  rest: number;
}

/** The header icon once every check finished, in place of the ring. */
export type ChecksEndIcon = "succeeded" | "requiredFailed";

export interface ChecksProgress {
  /** The ring to draw, or `null` to show the spinner while a run starts. */
  ring: ChecksRing | null;
  /** Set when every check finished and the outcome has its own icon. */
  end: ChecksEndIcon | null;
  /** Checks that finished, whatever the outcome: the suffix's `N`. */
  complete: number;
  /** Checks that run or will run: the suffix's `M`. */
  counted: number;
}

/**
 * How a run's checks show as the header icon and its `(N/M)` count. One place
 * decides both, so they always agree:
 *
 * - the ring draws finished checks only: passed green, failed red,
 *   incomplete amber, skipped grey; unfinished checks leave a gap, so a run
 *   with none finished shows the spinner;
 * - once every check finished, ✓ replaces the ring when all succeeded, and ⊗
 *   when a required check failed;
 * - not-applicable checks do not run for this form, so nothing counts them.
 *
 * A run that is starting has no checks yet, so it asks for the spinner itself.
 */
export function checksProgress(
  counts: Record<DraftCheckStateKind, number>,
  status: ConnectorChecksStatus,
  requiredFailed: boolean
): ChecksProgress {
  const ring: ChecksRing = {
    success: counts.passed,
    error: counts.failed,
    warning: counts.incomplete + counts.indeterminate,
    neutral: counts.skipped,
    // A stopped check has not run.
    rest: counts.running + counts.pending + counts.waiting + counts.stopped,
  };
  const counted: number =
    ring.success + ring.error + ring.warning + ring.neutral + ring.rest;
  const complete: number = counted - ring.rest;
  const allFinished: boolean =
    counted > 0 && complete === counted && status !== "running";
  const end: ChecksEndIcon | null = !allFinished
    ? null
    : requiredFailed
      ? "requiredFailed"
      : counts.passed === counted
        ? "succeeded"
        : null;
  return {
    ring: counted === 0 && status === "running" ? null : ring,
    end,
    complete,
    counted,
  };
}
