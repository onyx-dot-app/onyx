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
  decided_via: null,
  is_live: true,
};
test("a pending request shows its header, details, and decisions inside the comet border", () => {
  const { container } = render(
    <ApprovalCard
      approval={{
        ...approval,
        display_payload: { channel: "#general" },
        expires_at: "2099-01-01T00:00:00Z",
      }}
    />
  );
  const trigger = screen.getByRole("button", {
    name: /^Approval requested: Send message in Slack/,
  });
  expect(trigger).toHaveAttribute("aria-expanded", "true");
  expect(trigger).toHaveTextContent(/Approve by \d{1,2}:\d{2}\s?[AP]M$/);
  expect(container.querySelector(".craft-comet")).not.toBeNull();
  expect(screen.getByText("#general")).toBeVisible();
  expect(
    screen
      .getAllByRole("button")
      .slice(1)
      .map((button) => button.textContent)
  ).toEqual(["Approve once", "Approve for session", "Reject"]);
});

// Decision submission
describe("Decision submission", () => {
  it("uses the shared decision endpoint for session approval", async () => {
    jest.mocked(postApprovalDecision).mockResolvedValue({
      ...approval,
      decision: "APPROVED",
      decided_via: "SESSION_GRANT",
      is_live: false,
    });
    const user = setupUser();
    render(<ApprovalCard approval={approval} />);
    await user.click(screen.getByRole("button", { name: /approve.*session/i }));
    expect(postApprovalDecision).toHaveBeenCalledWith(
      "request",
      "approve_session"
    );
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(
        "Approved for this session: Send message in Slack"
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
    expect(screen.getByRole("status")).toHaveTextContent(
      "Timed out: Send message in Slack"
    );
    expect(
      screen.queryByRole("button", { name: /approve.*once/i })
    ).not.toBeInTheDocument();
  });
  it("treats abandoned undecided requests outside the live window as expired", () => {
    render(<ApprovalCard approval={{ ...approval, is_live: false }} />);
    expect(screen.getByRole("status")).toHaveTextContent(
      "Timed out: Send message in Slack"
    );
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

test("expired outcomes leave a one-line neutral record", () => {
  const { container } = render(
    <ApprovalCard
      approval={{ ...approval, decision: "EXPIRED", is_live: false }}
    />
  );
  expect(screen.getByRole("status")).toHaveTextContent(
    "Timed out: Send message in Slack"
  );
  expect(container.querySelector(".craft-comet")).toBeNull();
  expect(container.querySelector(".border-status-error-03")).toBeNull();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
  expect(screen.queryByText("No payload.")).not.toBeInTheDocument();
});
