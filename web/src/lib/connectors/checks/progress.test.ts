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

it("shows the spinner until a check starts", () => {
  expect(checksProgress(counts({}), "running").ring).toBeNull();
  expect(checksProgress(counts({ pending: 2, waiting: 1 }), "running")).toEqual(
    { ring: null, passed: 0, counted: 3 }
  );
});

it("shows a full green ring for a finished run with nothing to check", () => {
  expect(checksProgress(counts({ not_applicable: 2 }), "passed")).toEqual({
    ring: { success: 1, error: 0, warning: 0, neutral: 0, rest: 0 },
    passed: 0,
    counted: 0,
  });
});
