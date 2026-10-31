/**
 * The checks card names why a run failed to run, and offers Cancel only while
 * the checks run.
 */
import { render, screen, setupUser } from "@tests/setup/test-utils";
import { CheckCardView } from "@/views/admin/connectors/AddConnectorPage/components/CredentialChecksCard";
import { NO_CHECKS } from "@/lib/connectors/checks/hooks";
import type { ConnectorChecksStatus } from "@/lib/connectors/checks/types";

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
