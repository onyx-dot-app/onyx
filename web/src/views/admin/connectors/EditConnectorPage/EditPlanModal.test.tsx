import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import EditPlanModal from "@/views/admin/connectors/EditConnectorPage/EditPlanModal";
import type { ConnectorEditPlanResponse } from "@/lib/connectors/edit/types";

const PLAN: ConnectorEditPlanResponse = {
  plan_id: "plan-1",
  cc_pair_id: 3,
  created_at: "2026-10-06T00:00:00Z",
  expires_at: "2026-10-07T00:00:00Z",
  validation_blocks_apply: false,
  plan: {
    field_changes: [{ field_name: "cql_query", field_class: "scope" }],
    changed_settings: [],
    steps: [
      {
        kind: "restart_attempt",
        required: true,
        reasons: ["attempt_running"],
        field_names: [],
        backfill: null,
      },
    ],
    reconciliation_choice: {
      field_names: ["cql_query"],
      options: ["prune", "full_reindex", "both", "nothing"],
    },
    credential_choice: null,
    notes: [
      {
        kind: "attempt_restarted",
        severity: "info",
        message: "An index attempt runs with the current settings.",
      },
    ],
    validation: null,
    dry_run_results: [],
    indexed_document_count: 42,
  },
};

test("applies with the chosen reconciliation and offers to plan again on a stale plan", async () => {
  const user = setupUser();
  const onApply = jest.fn().mockResolvedValue({
    kind: "stale",
    detail: "The connector changed after planning.",
  });
  const onReplan = jest.fn().mockResolvedValue(undefined);

  render(
    <EditPlanModal
      planResponse={PLAN}
      onApply={onApply}
      onReplan={onReplan}
      onClose={jest.fn()}
    />
  );

  // The tooltip of a disabled Apply wraps the button, so query it anew.
  const applyButton = () => screen.getByRole("button", { name: "Apply" });
  expect(applyButton()).toBeDisabled();

  await user.click(screen.getByRole("radio", { name: "Prune" }));
  expect(applyButton()).toBeEnabled();
  await user.click(applyButton());

  expect(onApply).toHaveBeenCalledWith({
    plan_id: "plan-1",
    reconciliation: "prune",
    credential_path: null,
    added_steps: [],
    dropped_steps: [],
  });
  expect(await screen.findByText("The connector changed")).toBeVisible();
  expect(applyButton()).toBeDisabled();

  await user.click(screen.getByRole("button", { name: "Plan again" }));
  await waitFor(() => expect(onReplan).toHaveBeenCalledTimes(1));
});

function renderPlan(planResponse: ConnectorEditPlanResponse) {
  render(
    <EditPlanModal
      planResponse={planResponse}
      onApply={jest.fn()}
      onReplan={jest.fn()}
      onClose={jest.fn()}
    />
  );
}

const PASSED_CHECK = {
  capability: "doc_permission_sync",
  check_id: "list_permissions",
  display_name: "List file permissions",
  required: true,
  status: "passed",
  message: "",
  remediation: null,
  docs_link: null,
} as const;

test("lists every validation check when an access type change passes", () => {
  renderPlan({
    ...PLAN,
    plan: {
      ...PLAN.plan,
      changed_settings: ["access_type"],
      validation: {
        validation_error: null,
        check_results: [PASSED_CHECK],
        unfinished_check_ids: [],
      },
    },
  });

  expect(screen.getByText("Validation passed")).toBeVisible();
  expect(screen.getByText("List file permissions")).toBeVisible();
  expect(screen.getByText("Passed")).toBeVisible();
});

test("shows failed checks and unfinished ones as pending with the still-running note", () => {
  const stillRunning = "Some checks did not finish in time.";
  renderPlan({
    ...PLAN,
    validation_blocks_apply: true,
    plan: {
      ...PLAN.plan,
      notes: [
        {
          kind: "checks_still_running",
          severity: "info",
          message: stillRunning,
        },
      ],
      validation: {
        validation_error: null,
        check_results: [
          {
            ...PASSED_CHECK,
            check_id: "list_groups",
            display_name: "List groups",
            status: "failed",
            message: "Missing scope",
          },
        ],
        unfinished_check_ids: ["list_permissions"],
      },
      dry_run_results: [PASSED_CHECK],
    },
  });

  expect(screen.getByText("Validation failed")).toBeVisible();
  expect(screen.getByText("Missing scope")).toBeVisible();
  expect(screen.getByText("List file permissions")).toBeVisible();
  expect(screen.getByText("Queued")).toBeVisible();
  expect(screen.getAllByText(stillRunning)).toHaveLength(1);
});

test("says when no setting that needs validation changed", () => {
  renderPlan(PLAN);

  expect(
    screen.getByText("Settings that need validation did not change.")
  ).toBeVisible();
});
