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
    incomplete: 0,
    indeterminate: 0,
    skipped: 0,
    waiting: 0,
    stopped: 0,
    not_applicable: 0,
    ...overrides,
  };
}

it("draws finished checks by outcome and leaves a gap for the rest", () => {
  expect(
    checksProgress(
      counts({
        passed: 3,
        failed: 1,
        indeterminate: 1,
        skipped: 1,
        running: 1,
        pending: 1,
        waiting: 2,
      }),
      "running",
      true
    )
  ).toEqual({
    ring: { success: 3, error: 1, warning: 1, neutral: 1, rest: 4 },
    end: null,
    complete: 6,
    counted: 10,
  });
});

it("does not count skipped checks as successful, and leaves out not-applicable ones", () => {
  expect(
    checksProgress(
      counts({ passed: 4, skipped: 2, not_applicable: 3 }),
      "passed",
      false
    )
  ).toEqual({
    ring: { success: 4, error: 0, warning: 0, neutral: 2, rest: 0 },
    end: null,
    complete: 6,
    counted: 6,
  });
});

it("asks for the spinner while a run starts", () => {
  expect(checksProgress(counts({}), "running", false).ring).toBeNull();
  // Checks not finished are all gap, which the ring itself shows as the spinner.
  expect(
    checksProgress(
      counts({ running: 1, pending: 2, waiting: 1 }),
      "running",
      false
    )
  ).toEqual({
    ring: { success: 0, error: 0, warning: 0, neutral: 0, rest: 4 },
    end: null,
    complete: 0,
    counted: 4,
  });
});

it("passes an empty ring for a finished run with nothing to check", () => {
  // The ring itself shows every count at 0 as a full green ring.
  expect(
    checksProgress(counts({ not_applicable: 2 }), "passed", false)
  ).toEqual({
    ring: { success: 0, error: 0, warning: 0, neutral: 0, rest: 0 },
    end: null,
    complete: 0,
    counted: 0,
  });
});

it("counts incomplete and legacy indeterminate checks as one warning", () => {
  const progress = checksProgress(
    counts({ incomplete: 1, indeterminate: 1, passed: 1 }),
    "passed",
    false
  );

  expect(progress.ring?.warning).toBe(2);
  expect(progress.complete).toBe(3);
  expect(progress.end).toBeNull();
});

it("ends on a check when every check succeeded", () => {
  expect(checksProgress(counts({ passed: 5 }), "passed", false).end).toBe(
    "succeeded"
  );
  // Not while the run still goes, even with every listed check done.
  expect(
    checksProgress(counts({ passed: 5 }), "running", false).end
  ).toBeNull();
});

it("ends on a stop sign when a required check failed", () => {
  expect(
    checksProgress(
      counts({ passed: 14, failed: 1, skipped: 10 }),
      "failed",
      true
    ).end
  ).toBe("requiredFailed");
  // An optional failure keeps the ring.
  expect(
    checksProgress(counts({ passed: 3, failed: 1 }), "passed", false).end
  ).toBeNull();
  // A required failure waits for the other checks to finish.
  expect(
    checksProgress(counts({ failed: 1, running: 1 }), "failed", true).end
  ).toBeNull();
});
