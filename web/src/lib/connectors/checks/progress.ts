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
  /** The ring to draw, or `null` to show the spinner. */
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
 * Nothing started yet shows the spinner. No checks at all, once the run is
 * done, shows a full green ring.
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
  const started: boolean = counted - ring.rest > 0;

  if (counted === 0) {
    return {
      ring:
        status === "running"
          ? null
          : { success: 1, error: 0, warning: 0, neutral: 0, rest: 0 },
      passed: 0,
      counted: 0,
    };
  }
  return { ring: started ? ring : null, passed: counts.passed, counted };
}
