import type {
  CapabilityReportSnapshot,
  DraftCheckRunSnapshot,
  DraftCheckState,
} from "@/lib/connectors/checks/types";

/**
 * One row of the checks card. A stored report row has only the four final
 * states; a draft run adds the in-flight and form-dependent ones.
 */
export interface CheckRowModel {
  check_id: string;
  display_name: string;
  required: boolean;
  state: DraftCheckState;
  message: string;
  remediation: string | null;
  docs_link: string | null;
  /** Fields a waiting check needs: missing ones first, then invalid ones. */
  waiting_for: string[];
}

export function rowsFromReport(
  snapshot: CapabilityReportSnapshot | null
): CheckRowModel[] {
  return (snapshot?.report?.check_results ?? []).map((result) => ({
    check_id: result.check_id,
    display_name: result.display_name,
    required: result.required,
    state: result.status,
    message: result.message,
    remediation: result.remediation,
    docs_link: result.docs_link,
    waiting_for: [],
  }));
}

export function rowsFromDraft(
  snapshot: DraftCheckRunSnapshot | null
): CheckRowModel[] {
  return (snapshot?.checks ?? []).map((check) => ({
    check_id: check.check_id,
    display_name: check.display_name,
    required: check.required,
    state: check.state,
    message: check.message,
    remediation: check.remediation,
    docs_link: check.docs_link,
    waiting_for: [...check.missing_fields, ...check.invalid_fields],
  }));
}

export type CheckStateCounts = Record<DraftCheckState, number>;

export function countCheckStates(rows: CheckRowModel[]): CheckStateCounts {
  const counts: CheckStateCounts = {
    pending: 0,
    running: 0,
    passed: 0,
    failed: 0,
    indeterminate: 0,
    skipped: 0,
    waiting: 0,
    not_applicable: 0,
  };
  for (const row of rows) counts[row.state] += 1;
  return counts;
}

/** Summary slots of the folded card, in display order. */
export type CheckSummarySlot =
  | "failed"
  | "unverified"
  | "inProgress"
  | "expected"
  | "skipped"
  | "successful";

/**
 * The non-zero summary counts in display order, e.g. "1 in progress, 2 more
 * expected, 1 skipped, 4 successful". A queued or waiting check is "more
 * expected"; a not-applicable check is left out.
 */
export function summarizeCheckStates(
  counts: CheckStateCounts
): Array<{ slot: CheckSummarySlot; count: number }> {
  const slots: Array<{ slot: CheckSummarySlot; count: number }> = [
    { slot: "failed", count: counts.failed },
    { slot: "unverified", count: counts.indeterminate },
    { slot: "inProgress", count: counts.running },
    { slot: "expected", count: counts.pending + counts.waiting },
    { slot: "skipped", count: counts.skipped },
    { slot: "successful", count: counts.passed },
  ];
  return slots.filter(({ count }) => count > 0);
}

/** The header count's denominator: every check that applies. */
export function applicableCheckCount(counts: CheckStateCounts): number {
  return (
    Object.values(counts).reduce((sum, n) => sum + n, 0) - counts.not_applicable
  );
}
