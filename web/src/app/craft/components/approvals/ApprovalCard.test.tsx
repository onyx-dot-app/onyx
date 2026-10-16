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
    expect(screen.getByText("Expired")).toBeInTheDocument();
    expect(screen.queryByText("Rejected")).not.toBeInTheDocument();
    expect(
      screen.getByText("Approval expired. This request did not run.")
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /approve.*once/i })
    ).not.toBeInTheDocument();
  });
  it("treats abandoned undecided requests outside the live window as expired", () => {
    render(<ApprovalCard approval={{ ...approval, is_live: false }} />);
    expect(screen.getByText("Expired")).toBeInTheDocument();
    expect(screen.queryByText("Rejected")).not.toBeInTheDocument();
    expect(
      screen.getByText("Approval expired. This request did not run.")
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
