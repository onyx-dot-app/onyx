import {
  applicableCheckCount,
  countCheckStates,
  summarizeCheckStates,
  type CheckRowModel,
} from "@/lib/connectors/checks/checkRows";
import type { DraftCheckState } from "@/lib/connectors/checks/types";

function rows(states: DraftCheckState[]): CheckRowModel[] {
  return states.map((state, index) => ({
    check_id: `check_${index}`,
    display_name: `Check ${index}`,
    required: true,
    state,
    message: "",
    remediation: null,
    docs_link: null,
    waiting_for: [],
  }));
}

describe("summarizeCheckStates", () => {
  it("counts queued and waiting checks as more expected, in order", () => {
    const counts = countCheckStates(
      rows([
        "passed",
        "passed",
        "passed",
        "passed",
        "running",
        "pending",
        "waiting",
        "skipped",
        "not_applicable",
      ])
    );
    expect(summarizeCheckStates(counts)).toEqual([
      { slot: "inProgress", count: 1 },
      { slot: "expected", count: 2 },
      { slot: "skipped", count: 1 },
      { slot: "successful", count: 4 },
    ]);
    expect(applicableCheckCount(counts)).toBe(8);
  });

  it("leads with failures and leaves out zero counts", () => {
    expect(
      summarizeCheckStates(
        countCheckStates(rows(["failed", "indeterminate", "passed"]))
      )
    ).toEqual([
      { slot: "failed", count: 1 },
      { slot: "unverified", count: 1 },
      { slot: "successful", count: 1 },
    ]);
  });
});
