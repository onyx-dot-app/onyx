import {
  getNonClickableReason,
  isScheduledRunContextInFlight,
} from "@/app/craft/v1/tasks/utils";
import type {
  ScheduledRunContextResponse,
  ScheduledRunSummary,
  ScheduledTaskRunStatus,
} from "@/app/craft/v1/tasks/interfaces";

function run(
  status: ScheduledTaskRunStatus,
  sessionId: string | null
): ScheduledRunSummary {
  return {
    id: `run-${status}`,
    status,
    trigger_source: "MANUAL_RUN_NOW",
    started_at: "2026-01-01T00:00:00Z",
    finished_at: null,
    session_id: sessionId,
    summary: null,
    skip_reason: null,
    error_class: null,
  };
}

function context(status: ScheduledTaskRunStatus): ScheduledRunContextResponse {
  return {
    run_id: `run-${status}`,
    task_id: "task-1",
    task_name: "Task",
    status,
    started_at: "2026-01-01T00:00:00Z",
    finished_at: null,
  };
}

describe("scheduled task run utils", () => {
  it.each(["RUNNING", "AWAITING_APPROVAL", "SUCCEEDED", "FAILED"] as const)(
    "allows opening %s runs with linked sessions",
    (status) => {
      expect(getNonClickableReason(run(status, "session-1"))).toBeNull();
    }
  );

  it("keeps queued and skipped runs blocked", () => {
    expect(getNonClickableReason(run("QUEUED", null))).toContain(
      "hasn't started"
    );
    expect(getNonClickableReason(run("SKIPPED", null))).toContain("skipped");
  });

  it("blocks openable statuses until a session exists", () => {
    expect(getNonClickableReason(run("RUNNING", null))).toContain(
      "has not created a session"
    );
  });

  it("treats only running and awaiting-approval contexts as in-flight", () => {
    expect(isScheduledRunContextInFlight(context("RUNNING"))).toBe(true);
    expect(isScheduledRunContextInFlight(context("AWAITING_APPROVAL"))).toBe(
      true
    );
    expect(isScheduledRunContextInFlight(context("SUCCEEDED"))).toBe(false);
    expect(isScheduledRunContextInFlight(context("FAILED"))).toBe(false);
  });
});
