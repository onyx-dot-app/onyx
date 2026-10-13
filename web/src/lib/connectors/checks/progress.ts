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
  /** Checks that finished, whatever the outcome: the suffix's `N`. */
  complete: number;
  /** Checks that run or will run: the suffix's `M`. */
  counted: number;
}

/**
 * How a run's checks show as the header ring and its `(N/M)` count. One place
 * decides both, so they always agree:
 *
 * - passed and skipped are green (finished, not blocking), failed red,
 *   indeterminate amber (it blocks, but is not a failure), running grey;
 * - pending and waiting checks have not started, so they leave a gap;
 * - the count is the finished checks out of every check that runs or will
 *   run, so it matches the ring's coloured share less the running arc;
 * - not-applicable checks do not run for this form, so neither counts them.
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
    success: counts.passed + counts.skipped,
    error: counts.failed,
    warning: counts.indeterminate,
    neutral: counts.running,
    rest: counts.pending + counts.waiting,
  };
  const counted: number =
    ring.success + ring.error + ring.warning + ring.neutral + ring.rest;
  return {
    ring: counted === 0 && status === "running" ? null : ring,
    complete:
      counts.passed + counts.failed + counts.indeterminate + counts.skipped,
    counted,
  };
}
