/**
 * Check rows read the result line the backend gives, with the guide's state
 * words as the fallback, and open to show both guidance texts. The card names
 * why a run failed and can stop one.
 */
import { render, screen, setupUser } from "@tests/setup/test-utils";
import {
  type CheckLine,
  CheckCardView,
  CheckLineGroups,
} from "@/views/admin/connectors/AddConnectorPage/components/CredentialChecksCard";
import { NO_CHECKS } from "@/lib/connectors/checks/hooks";
import type { ConnectorChecksStatus } from "@/lib/connectors/checks/types";

function line(
  overrides: Partial<CheckLine> & Pick<CheckLine, "state">
): CheckLine {
  return {
    capability: "indexing",
    check_id: "sign_in",
    display_name: "Sign in to Confluence",
    required: true,
    message: "",
    summary: null,
    description: null,
    remediation: null,
    docs_link: null,
    ...overrides,
  };
}

test("shows the result line in place of the state word or the raw message", () => {
  render(
    <CheckLineGroups
      lines={[
        line({ state: "passed", summary: "34 spaces visible" }),
        line({
          check_id: "auth",
          state: "failed",
          message: "Confluence rejected the credential (invalid_auth).",
          summary: "Sign-in rejected",
        }),
      ]}
    />
  );

  expect(screen.getByText("34 spaces visible")).toBeInTheDocument();
  expect(screen.getByText("Sign-in rejected")).toBeInTheDocument();
  expect(screen.queryByText("Successful")).not.toBeInTheDocument();
  expect(screen.queryByText(/invalid_auth/)).not.toBeInTheDocument();
});

test("reads incomplete and legacy indeterminate checks as Incomplete", () => {
  render(
    <CheckLineGroups
      lines={[
        line({ state: "incomplete" }),
        line({ check_id: "legacy", state: "indeterminate" }),
      ]}
    />
  );

  expect(screen.getByText("2 Incomplete")).toBeInTheDocument();
  expect(screen.getAllByText("Incomplete")).toHaveLength(2);
});

test("a failed row opens to show both the description and the repair step", async () => {
  const user = setupUser();
  render(
    <CheckLineGroups
      lines={[
        line({
          state: "failed",
          summary: "Invalid channel pattern: [a",
          description: "Indexing cannot filter channels with this pattern.",
          remediation: "Fix the channel regex in the connector settings.",
        }),
      ]}
    />
  );

  await user.click(screen.getByText("Invalid channel pattern: [a"));

  expect(
    screen.getByText("Indexing cannot filter channels with this pattern.")
  ).toBeInTheDocument();
  expect(
    screen.getByText("Fix the channel regex in the connector settings.")
  ).toBeInTheDocument();
});

test("a successful row opens to show its description", async () => {
  const user = setupUser();
  render(
    <CheckLineGroups
      lines={[
        line({
          state: "passed",
          summary: "Signed in",
          description: "The app can read only the sites it was granted.",
        }),
      ]}
    />
  );

  await user.click(screen.getByText("Signed in"));

  expect(
    screen.getByText("The app can read only the sites it was granted.")
  ).toBeInTheDocument();
});

function renderCardView(
  status: ConnectorChecksStatus,
  props: { failureReason?: string; onCancel?: () => void } = {}
) {
  render(
    <CheckCardView
      status={status}
      results={[]}
      openChecks={[]}
      inProgressCount={0}
      expectedCount={0}
      stateCounts={NO_CHECKS}
      onRerun={jest.fn()}
      {...props}
    />
  );
}

test("names the server's reason when the run failed to run", () => {
  const reason = "Credential 26 is shared with you.";
  renderCardView("failedToRun", { failureReason: reason });

  expect(screen.getAllByText(reason).length).toBeGreaterThan(0);
  expect(
    screen.queryByText("Checks failed to run. Try again.")
  ).not.toBeInTheDocument();
});

test("offers Cancel only while the checks run", async () => {
  const user = setupUser();
  const onCancel = jest.fn();
  renderCardView("running", { onCancel });

  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(onCancel).toHaveBeenCalledTimes(1);
});

test("offers no Cancel once the checks finished", () => {
  renderCardView("passed", { onCancel: jest.fn() });

  expect(screen.queryByRole("button", { name: "Cancel" })).toBeNull();
});
