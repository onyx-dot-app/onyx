import { checksProgress } from "@/lib/connectors/checks/progress";
import type { DraftCheckStateKind } from "@/lib/connectors/checks/types";

function counts(
  overrides: Partial<Record<DraftCheckStateKind, number>>
): Record<DraftCheckStateKind, number> {
  return {
    pending: 0,
    running: 0,
    passed: 0,
    failed: 0,
    indeterminate: 0,
    skipped: 0,
    waiting: 0,
    not_applicable: 0,
    ...overrides,
  };
}

it("colours outcomes and leaves a gap for checks not started", () => {
  expect(
    checksProgress(
      counts({
        passed: 3,
        failed: 1,
        indeterminate: 1,
        running: 1,
        pending: 1,
        waiting: 2,
      }),
      "running"
    )
  ).toEqual({
    ring: { success: 3, error: 1, warning: 1, neutral: 1, rest: 3 },
    passed: 3,
    counted: 9,
  });
});

it("leaves skipped and not-applicable checks out of the ring and the count", () => {
  expect(
    checksProgress(
      counts({ passed: 4, skipped: 2, not_applicable: 3 }),
      "passed"
    )
  ).toEqual({
    ring: { success: 4, error: 0, warning: 0, neutral: 0, rest: 0 },
    passed: 4,
    counted: 4,
  });
});

it("asks for the spinner while a run starts", () => {
  expect(checksProgress(counts({}), "running").ring).toBeNull();
  // Checks not started are all gap, which the ring itself shows as the spinner.
  expect(checksProgress(counts({ pending: 2, waiting: 1 }), "running")).toEqual(
    {
      ring: { success: 0, error: 0, warning: 0, neutral: 0, rest: 3 },
      passed: 0,
      counted: 3,
    }
  );
});

it("passes an empty ring for a finished run with nothing to check", () => {
  // The ring itself shows every count at 0 as a full green ring.
  expect(checksProgress(counts({ not_applicable: 2 }), "passed")).toEqual({
    ring: { success: 0, error: 0, warning: 0, neutral: 0, rest: 0 },
    passed: 0,
    counted: 0,
  });
});
