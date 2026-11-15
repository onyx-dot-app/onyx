import {
  act,
  fireEvent,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import ToolApprovalCard from "@/app/app/message/messageComponents/ToolApprovalCard";
import { type ToolApproval, useToolApprovalUi } from "@/lib/chat/toolApprovals";
import {
  PacketType,
  ToolApprovalRequest,
} from "@/app/app/services/streamingModels";
import type { ApprovalDecisionResponse } from "@/lib/chat/types";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import { followApprovalContinuation } from "@/lib/chat/settleChatSession";
import messages from "@/i18n/messages/en.json";

jest.mock("@/lib/chat/settleChatSession", () => ({
  followApprovalContinuation: jest.fn(),
}));

const copy = messages.common.approvalCard;

/** The one-line record a decided request leaves. */
function record(status: keyof typeof copy.record): string {
  return copy.record[status].replace("{headline}", "Create issue");
}

const request: ToolApprovalRequest = {
  type: PacketType.TOOL_APPROVAL_REQUEST,
  approval_id: "approval-1",
  tool_call_id: "call-1",
  tool_name: "mcp__3__github__create_issue",
  display_name: "Create issue",
  arguments: { title: "Fix login", labels: ["bug", "p1"] },
  agent_name: null,
};
const approval: ToolApproval = { turnIndex: 1, status: "pending", request };

/** A waiting card as the trailing region renders it: a decision this client
 * made decides its status. */
function Harness({ agentName = null }: { agentName?: string | null }) {
  const status = useToolApprovalUi((state) =>
    state.localStatuses.get(request.approval_id)
  );
  return (
    <ToolApprovalCard
      approval={{
        ...approval,
        request: { ...request, agent_name: agentName },
        status: status ?? "pending",
      }}
    />
  );
}

function respond(status: number, body: unknown) {
  return jest
    .spyOn(global, "fetch")
    .mockResolvedValue(new Response(JSON.stringify(body), { status }));
}

function decided(
  decision: ApprovalDecisionResponse["decision"],
  decidedVia: ApprovalDecisionResponse["decided_via"] = "USER"
): ApprovalDecisionResponse {
  return { approval_id: "approval-1", decision, decided_via: decidedVia };
}

async function clickApprove() {
  await setupUser().click(
    screen.getByRole("button", { name: copy.approveOnce.ariaLabel })
  );
}

beforeEach(() => {
  useToolApprovalUi.setState({ localStatuses: new Map(), nudge: null });
  useChatSessionStore.setState({ currentSessionId: "session" });
});
afterEach(() => jest.restoreAllMocks());

describe("Pending request", () => {
  it("names the tool and shows the arguments", () => {
    render(<Harness />);

    expect(
      screen.getByRole("button", {
        name: /^Approval requested: Create issue/,
      })
    ).toBeInTheDocument();
    expect(screen.getByText("Fix login")).toBeVisible();
    expect(screen.getByText("bug, p1")).toBeVisible();
  });
});

describe("Background agent request", () => {
  it("names the agent that wants to run the tool", () => {
    render(<Harness agentName="Researcher" />);

    expect(
      screen.getByText("Researcher wants to run Create issue")
    ).toBeVisible();
  });

  it.each([
    ["the reply's own request follows", null, 1],
    ["a background agent's request does not follow", "Researcher", 0],
  ] as const)(
    "after a decision, %s the continuation stream",
    async (_, agentName, calls) => {
      respond(200, decided("APPROVED"));
      render(<Harness agentName={agentName} />);

      await clickApprove();

      await waitFor(() =>
        expect(screen.getByRole("status")).toHaveTextContent(record("approved"))
      );
      expect(followApprovalContinuation).toHaveBeenCalledTimes(calls);
    }
  );
});

describe("Decision outcomes", () => {
  it("posts the decision and shows the server's answer before the resolution arrives", async () => {
    const fetchMock = respond(200, decided("APPROVED", "SESSION_GRANT"));
    render(<Harness />);

    await setupUser().click(
      screen.getByRole("button", { name: copy.approveChat.tooltip })
    );

    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(
        record("approvedForChat")
      )
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/chat/approvals/approval-1/decision",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ decision: "approve_session" }),
      })
    );
  });

  it("shows a disabled tool when the policy rejects the approval", async () => {
    respond(200, decided("REJECTED", "POLICY"));
    render(<Harness />);

    await clickApprove();

    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(record("disabled"))
    );
  });

  it.each([409, 404])(
    "closes the request without the raw detail for a %s response",
    async (status) => {
      respond(status, { detail: "raw backend detail" });
      render(<Harness />);

      await clickApprove();

      await waitFor(() =>
        expect(screen.getByRole("status")).toHaveTextContent(record("closed"))
      );
      expect(screen.queryByText("raw backend detail")).not.toBeInTheDocument();
    }
  );

  it("keeps the request actionable after another failure", async () => {
    jest.spyOn(console, "error").mockImplementation(() => {});
    respond(500, { detail: "raw backend detail" });
    render(<Harness />);

    await clickApprove();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      copy.submitError
    );
    expect(
      screen.getByRole("button", { name: copy.approveOnce.ariaLabel })
    ).toBeEnabled();
  });
});

describe("Blocked send", () => {
  function mockReducedMotion(reduce: boolean) {
    jest.spyOn(window, "matchMedia").mockImplementation(
      (query) =>
        ({
          matches: reduce && query === "(prefers-reduced-motion: reduce)",
          media: query,
        }) as MediaQueryList
    );
  }

  it.each([
    [false, "smooth"],
    [true, "auto"],
  ] as const)(
    "scrolls the nudged card into view and shakes it (reduced motion: %s)",
    async (reduce, behavior) => {
      mockReducedMotion(reduce);
      const scrollIntoView = jest.fn();
      Element.prototype.scrollIntoView = scrollIntoView;
      render(<ToolApprovalCard approval={approval} />);
      const card = screen.getByTestId("tool-approval-card");

      act(() => useToolApprovalUi.getState().nudgeApproval("other-approval"));
      expect(scrollIntoView).not.toHaveBeenCalled();

      act(() => useToolApprovalUi.getState().nudgeApproval("approval-1"));
      expect(scrollIntoView).toHaveBeenCalledWith({
        behavior,
        block: "center",
      });
      await waitFor(() =>
        expect(card).toHaveClass("motion-safe:animate-shake")
      );

      // A second nudge removes the class for one frame to restart the shake.
      act(() => useToolApprovalUi.getState().nudgeApproval("approval-1"));
      expect(card).not.toHaveClass("motion-safe:animate-shake");
      await waitFor(() =>
        expect(card).toHaveClass("motion-safe:animate-shake")
      );

      fireEvent.animationEnd(card);
      expect(card).not.toHaveClass("motion-safe:animate-shake");
    }
  );

  it("does not repeat a handled nudge when the card mounts again", () => {
    mockReducedMotion(false);
    const scrollIntoView = jest.fn();
    Element.prototype.scrollIntoView = scrollIntoView;
    const first = render(<ToolApprovalCard approval={approval} />);
    act(() => useToolApprovalUi.getState().nudgeApproval("approval-1"));
    expect(scrollIntoView).toHaveBeenCalledTimes(1);
    first.unmount();

    render(<ToolApprovalCard approval={approval} />);

    expect(scrollIntoView).toHaveBeenCalledTimes(1);
    expect(useToolApprovalUi.getState().nudge).toBeNull();
  });
});
