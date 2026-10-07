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

export interface ChecksProgress {
  /** The ring to draw, or `null` to show the spinner while a run starts. */
  ring: ChecksRing | null;
  /** Checks that passed, for the `(passed/counted)` suffix. */
  passed: number;
  /** Checks the ring and the suffix count. */
  counted: number;
}

/**
 * How a run's checks show as the header ring and its `(N/M)` count. One place
 * decides both, so they always agree:
 *
 * - passed is green, failed red, indeterminate amber (it blocks, but is not a
 *   failure), running grey;
 * - pending and waiting checks have not started, so they leave a gap;
 * - skipped and not-applicable checks are not counted: neither blocks, and a
 *   finished run would otherwise never fill the ring.
 *
 * The ring shows the spinner while nothing has started, and a full green
 * ring when there is nothing to count. A run that is starting has no checks
 * yet, so it asks for the spinner itself.
 */
export function checksProgress(
  counts: Record<DraftCheckStateKind, number>,
  status: ConnectorChecksStatus
): ChecksProgress {
  const ring: ChecksRing = {
    success: counts.passed,
    error: counts.failed,
    warning: counts.indeterminate,
    neutral: counts.running,
    rest: counts.pending + counts.waiting,
  };
  const counted: number =
    ring.success + ring.error + ring.warning + ring.neutral + ring.rest;
  return {
    ring: counted === 0 && status === "running" ? null : ring,
    passed: counts.passed,
    counted,
  };
}
