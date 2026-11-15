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
import { followChatStream } from "@/lib/chat/settleChatSession";
import { readChatSessionStatus } from "@/lib/chat/sessionReadiness";
import type { ChatSessionStatus } from "@/lib/chat/types";
import type { ChatStream } from "@/app/app/types";
import messages from "@/i18n/messages/en.json";
import useSWR from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";

jest.mock("@/lib/chat/settleChatSession", () => ({
  followChatStream: jest.fn(),
}));
jest.mock("@/lib/chat/sessionReadiness", () => ({
  readChatSessionStatus: jest.fn(),
}));

const continuation: ChatStream = { stream_id: 900, response_ids: [82] };

function status(processing: boolean): ChatSessionStatus {
  return {
    is_processing: processing,
    current_stream: processing ? continuation : null,
    has_active_subagents: false,
    has_startable_input: false,
    latest_response_id: 82,
    approvals_version: "2",
  };
}

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

/** Status reads of the chat's status subscriber, as the chat queue mounts it. */
const statusReads = jest.fn(async () => status(false));

/** A waiting card as the trailing region renders it: a decision this client
 * made decides its status. */
function Harness({ agentName = null }: { agentName?: string | null }) {
  const status = useToolApprovalUi((state) =>
    state.localStatuses.get(request.approval_id)
  );
  useSWR(SWR_KEYS.chatSessionStatus("session"), statusReads, {
    revalidateOnMount: false,
  });
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
  decidedVia: ApprovalDecisionResponse["decided_via"] = "USER",
  next: ChatStream | null = null
): ApprovalDecisionResponse {
  return {
    approval_id: "approval-1",
    decision,
    decided_via: decidedVia,
    continuation: next,
  };
}

async function clickApprove() {
  await setupUser().click(
    screen.getByRole("button", { name: copy.approveOnce.ariaLabel })
  );
}

beforeEach(() => {
  useToolApprovalUi.setState({
    localStatuses: new Map(),
    nudge: null,
  });
  statusReads.mockClear();
  useChatSessionStore.setState({ currentSessionId: "session" });
  jest.mocked(followChatStream).mockReset();
  jest.mocked(readChatSessionStatus).mockReset();
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
});

describe("Continuation", () => {
  it.each([
    ["follows the stream the server names", continuation],
    ["follows nothing while the server names no stream", null],
  ] as const)("after a decision, %s", async (_, next) => {
    respond(200, decided("APPROVED", "USER", next));
    render(<Harness />);

    await clickApprove();

    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(record("approved"))
    );
    if (next)
      expect(followChatStream).toHaveBeenCalledWith(
        "session",
        next,
        expect.any(String)
      );
    else expect(followChatStream).not.toHaveBeenCalled();
    expect(readChatSessionStatus).not.toHaveBeenCalled();
  });

  it.each([
    ["reads the chat's status for the resumed agent", "Researcher", null],
    ["leaves a root request to its continuation", null, null],
    ["follows the agent's named stream instead", "Researcher", continuation],
  ] as const)("after a decision, %s", async (_, agentName, next) => {
    respond(200, decided("APPROVED", "USER", next));
    render(<Harness agentName={agentName} />);

    await clickApprove();

    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(record("approved"))
    );
    const agentWithoutStream = agentName !== null && next === null;
    await waitFor(() =>
      expect(statusReads).toHaveBeenCalledTimes(agentWithoutStream ? 1 : 0)
    );
  });

  it.each([
    ["follows the running stream", true],
    ["follows nothing while the chat is idle", false],
  ] as const)(
    "after a refused decision, reads the status once and %s",
    async (_, processing) => {
      jest.mocked(readChatSessionStatus).mockResolvedValue(status(processing));
      respond(409, { detail: "already decided" });
      render(<Harness />);

      await clickApprove();

      await waitFor(() =>
        expect(screen.getByRole("status")).toHaveTextContent(record("closed"))
      );
      await waitFor(() =>
        expect(readChatSessionStatus).toHaveBeenCalledWith("session")
      );
      expect(readChatSessionStatus).toHaveBeenCalledTimes(1);
      // Lets the decision handler finish after the status read.
      await act(async () => {});
      if (processing)
        await waitFor(() =>
          expect(followChatStream).toHaveBeenCalledWith(
            "session",
            continuation,
            expect.any(String)
          )
        );
      else expect(followChatStream).not.toHaveBeenCalled();
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
    async (code) => {
      jest.mocked(readChatSessionStatus).mockResolvedValue(status(false));
      respond(code, { detail: "raw backend detail" });
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
