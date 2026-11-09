import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import ApprovalCard from "@/app/craft/components/approvals/ApprovalCard";
import { postApprovalDecision } from "@/app/craft/services/apiServices";
import type { ApprovalView } from "@/app/craft/types/approvals";
jest.mock("@/app/craft/services/apiServices", () => ({
  postApprovalDecision: jest.fn(),
  ApprovalConflictError: class extends Error {},
}));
const approval: ApprovalView = {
  approval_id: "request",
  session_id: "session",
  actions: [
    {
      action_type: "send",
      display_name: "Send message",
      description: "",
      policy: "ASK",
    },
  ],
  app_name: "Slack",
  payload: {},
  display_payload: {},
  created_at: "2026-10-01T00:00:00Z",
  expires_at: null,
  decision: null,
  decided_at: null,
  is_live: true,
};
// Decision submission
describe("Decision submission", () => {
  it("uses the shared decision endpoint for session approval", async () => {
    const user = setupUser();
    render(<ApprovalCard approval={approval} />);
    await user.click(screen.getByRole("button", { name: /approve.*session/i }));
    await waitFor(() =>
      expect(postApprovalDecision).toHaveBeenCalledWith(
        "request",
        "approve_session"
      )
    );
  });
});

// Expiry
describe("Expiry", () => {
  it("shows expired requests without approval controls", () => {
    render(
      <ApprovalCard
        approval={{ ...approval, is_live: false, decision: "EXPIRED" }}
      />
    );
    expect(screen.queryByText("Rejected")).not.toBeInTheDocument();
    expect(
      screen.getByText("Approval timed out. The action did not run.")
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /approve.*once/i })
    ).not.toBeInTheDocument();
  });
  it("treats abandoned undecided requests outside the live window as expired", () => {
    render(<ApprovalCard approval={{ ...approval, is_live: false }} />);
    expect(screen.queryByText("Rejected")).not.toBeInTheDocument();
    expect(
      screen.getByText("Approval timed out. The action did not run.")
    ).toBeInTheDocument();
  });

  it("keeps server-live approvals actionable when the device clock is ahead", () => {
    render(
      <ApprovalCard
        approval={{
          ...approval,
          expires_at: new Date(Date.now() - 600_000).toISOString(),
        }}
      />
    );
    expect(
      screen.getByRole("button", { name: /approve.*once/i })
    ).toBeEnabled();
    expect(screen.queryByText("Expired")).not.toBeInTheDocument();
  });
});

// Session approval eligibility
describe("Session approval eligibility", () => {
  it("does not offer session approval for unidentified actions", () => {
    render(
      <ApprovalCard
        approval={{ ...approval, can_approve_for_session: false }}
      />
    );
    expect(
      screen.queryByRole("button", { name: /approve.*session/i })
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /approve.*once/i })
    ).toBeEnabled();
  });
});

test("expired outcomes use a collapsed neutral row with expandable details", async () => {
  const user = setupUser();
  const { container } = render(
    <ApprovalCard
      approval={{ ...approval, decision: "EXPIRED", is_live: false }}
    />
  );
  const row = screen.getByRole("button", { name: /Approval timed out/ });
  expect(row).toHaveAttribute("aria-expanded", "false");
  expect(screen.getByText("Send message in Slack")).toBeVisible();
  expect(container.querySelector(".craft-comet")).toBeNull();
  expect(container.querySelector(".border-status-error-03")).toBeNull();
  expect(screen.queryByText("No payload.")).not.toBeInTheDocument();
  await user.click(row);
  expect(row).toHaveAttribute("aria-expanded", "true");
  expect(await screen.findByText("No payload.")).toBeVisible();
});
