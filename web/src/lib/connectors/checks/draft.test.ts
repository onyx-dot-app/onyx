import {
  bindingChecksGate,
  bindingChecksVerdict,
  requiredChecksStatus,
} from "@/lib/connectors/checks/draft";
import { ValidSources } from "@/lib/connectors/types/source";
import type {
  DraftCheck,
  DraftCheckRunSnapshot,
  DraftRunStatus,
} from "@/lib/connectors/checks/types";

function check(overrides: Partial<DraftCheck>): DraftCheck {
  return {
    check_id: "check",
    display_name: "Check",
    capability: "indexing",
    required: true,
    state: "passed",
    message: "",
    missing_fields: [],
    invalid_fields: [],
    remediation: null,
    docs_link: null,
    duration_ms: null,
    from_cache: false,
    validates_binding: false,
    ...overrides,
  };
}

function snapshot(
  checks: DraftCheck[],
  status: DraftRunStatus = "completed"
): DraftCheckRunSnapshot {
  return {
    run_id: "run",
    draft_key: "draft",
    source: ValidSources.Slack,
    credential_id: 1,
    access_type: "public",
    status,
    form_errors: {},
    unknown_fields: [],
    checks,
  };
}

describe("requiredChecksStatus", () => {
  it("is pending before any run", () => {
    expect(requiredChecksStatus(null)).toBe("pending");
  });

  it("is ok when every required check passed", () => {
    expect(
      requiredChecksStatus(
        snapshot([
          check({ state: "passed" }),
          check({ required: false, state: "failed" }),
          check({ state: "indeterminate" }),
          check({ state: "not_applicable" }),
        ])
      )
    ).toBe("ok");
  });

  it("is pending while a required check runs", () => {
    expect(
      requiredChecksStatus(snapshot([check({ state: "running" })], "running"))
    ).toBe("pending");
    expect(
      requiredChecksStatus(snapshot([check({ state: "passed" })], "running"))
    ).toBe("pending");
  });

  it("is failed as soon as a required check fails", () => {
    expect(
      requiredChecksStatus(
        snapshot(
          [check({ state: "failed" }), check({ state: "pending" })],
          "running"
        )
      )
    ).toBe("failed");
  });

  it("fails a required check waiting on an invalid field", () => {
    expect(
      requiredChecksStatus(
        snapshot([check({ state: "waiting", invalid_fields: ["channels"] })])
      )
    ).toBe("failed");
  });

  it("does not block on a required check waiting on a missing field", () => {
    expect(
      requiredChecksStatus(
        snapshot([check({ state: "waiting", missing_fields: ["channels"] })])
      )
    ).toBe("ok");
  });

  it("is unavailable when the run could not start", () => {
    expect(
      requiredChecksStatus(
        snapshot([check({ state: "pending" })], "failed_to_run")
      )
    ).toBe("unavailable");
  });

  it("is pending when a newer run superseded this one", () => {
    expect(
      requiredChecksStatus(snapshot([check({ state: "passed" })], "superseded"))
    ).toBe("pending");
  });
});

function binding(overrides: Partial<DraftCheck>): DraftCheck {
  return check({ validates_binding: true, ...overrides });
}

describe("bindingChecksVerdict", () => {
  it("counts only required binding checks that apply", () => {
    expect(
      bindingChecksVerdict(
        snapshot([
          check({ state: "failed" }),
          binding({ required: false, state: "failed" }),
          binding({ state: "not_applicable" }),
        ])
      )
    ).toBe("none");
  });

  it("passes on passed and indeterminate binding checks", () => {
    expect(
      bindingChecksVerdict(
        snapshot([
          binding({ state: "passed" }),
          binding({ state: "indeterminate" }),
          check({ state: "pending" }),
        ])
      )
    ).toBe("passed");
  });

  it("is checking while a binding check is unfinished", () => {
    expect(
      bindingChecksVerdict(
        snapshot(
          [binding({ state: "passed" }), binding({ state: "running" })],
          "running"
        )
      )
    ).toBe("checking");
  });

  it("fails as soon as a binding check fails", () => {
    expect(
      bindingChecksVerdict(
        snapshot(
          [binding({ state: "failed" }), binding({ state: "pending" })],
          "running"
        )
      )
    ).toBe("failed");
  });

  it("is unavailable when the run could not start", () => {
    expect(
      bindingChecksVerdict(
        snapshot([binding({ state: "pending" })], "failed_to_run")
      )
    ).toBe("unavailable");
  });
});

describe("bindingChecksGate", () => {
  const base = {
    current: true,
    passedBefore: false,
    requestFailed: false,
    failedMessage: "Failed.",
  };

  it("unlocks when the current run's binding checks pass", () => {
    expect(
      bindingChecksGate({
        ...base,
        snapshot: snapshot([binding({ state: "passed" })]),
      }).status
    ).toBe("unlocked");
  });

  it("is checking for a run of other bound values", () => {
    expect(
      bindingChecksGate({
        ...base,
        current: false,
        snapshot: snapshot([binding({ state: "passed" })]),
      }).status
    ).toBe("checking");
  });

  it("keeps an earlier pass while a later run is unfinished", () => {
    expect(
      bindingChecksGate({
        ...base,
        passedBefore: true,
        snapshot: snapshot([binding({ state: "running" })], "running"),
      }).status
    ).toBe("unlocked");
  });

  it("locks with the message when a binding check fails", () => {
    expect(
      bindingChecksGate({
        ...base,
        passedBefore: true,
        snapshot: snapshot([binding({ state: "failed" })]),
      })
    ).toEqual({
      status: "locked",
      reason: { kind: "custom", message: "Failed." },
    });
  });

  it("unlocks when the draft-run request failed", () => {
    expect(
      bindingChecksGate({ ...base, snapshot: null, requestFailed: true }).status
    ).toBe("unlocked");
  });
});
