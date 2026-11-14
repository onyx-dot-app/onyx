import { beforeEach, describe, expect, it, jest } from "@jest/globals";
import type { Mock } from "jest-mock";
import type { ReactElement } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render as renderView,
  waitFor,
} from "@testing-library/react-native";

import { postApprovalDecision } from "@/api/chat/approvals";
import { ApiError } from "@/api/errors";
import type { Message } from "@/chat/interfaces";
import {
  Packet,
  PacketType,
  StopReason,
  ToolApprovalRequest,
} from "@/chat/streamingModels";
import {
  ApprovalDecision,
  ApprovalStatus,
  ToolApproval,
  useToolApprovalUi,
} from "@/chat/toolApprovals";
import { MessageRow } from "@/components/chat/MessageRow";
import { ToolApprovalCard } from "@/components/chat/ToolApprovalCard";
import { recoverChatSession } from "@/hooks/useChatSessionController";
import { useChatSessionStore } from "@/state/chatSessionStore";

jest.mock("@/api/chat/approvals", () => ({ postApprovalDecision: jest.fn() }));
jest.mock("@/hooks/useChatSessionController", () => ({
  recoverChatSession: jest.fn(),
}));
// These reach native modules that jest cannot load.
jest.mock("@/state/storage");
jest.mock("@/components/chat/StreamingMarkdown", () => ({}));

const postMock = postApprovalDecision as unknown as Mock<
  (
    approvalId: string,
    decision: string,
  ) => Promise<{ decision: string; decided_via?: string }>
>;

const request: ToolApprovalRequest = {
  type: "tool_approval_request",
  approval_id: "a1",
  tool_call_id: "c1",
  tool_name: "lookup",
  display_name: "Lookup",
  arguments: { query: "weather", limit: 3, filters: { site: "docs" } },
};

function render(element: ReactElement) {
  return renderView(
    <QueryClientProvider client={new QueryClient()}>
      {element}
    </QueryClientProvider>,
  );
}

function approval(status: ApprovalStatus = "pending"): ToolApproval {
  return { turnIndex: 0, request, status };
}

describe("ToolApprovalCard", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useToolApprovalUi.setState({ localStatuses: new Map(), nudgeSeq: 0 });
  });

  it("shows a pending request with its arguments and decisions", () => {
    const view = render(<ToolApprovalCard approval={approval()} />);

    expect(view.getByText("Approval requested: Lookup")).toBeTruthy();
    expect(view.getByText("query")).toBeTruthy();
    expect(view.getByText("weather")).toBeTruthy();
    expect(view.getByText("3")).toBeTruthy();
    expect(view.getByText(/"site": "docs"/)).toBeTruthy();
    expect(view.getByLabelText("Approve this action once")).toBeTruthy();
    expect(
      view.getByLabelText(
        "Approve now and run this tool without asking again for the rest of this chat",
      ),
    ).toBeTruthy();
    expect(view.getByLabelText("Reject this action")).toBeTruthy();
  });

  it.each<[ApprovalStatus, string]>([
    ["approved", "Approved: Lookup"],
    ["approvedForSession", "Approved for this chat: Lookup"],
    ["rejected", "Not approved: Lookup"],
    ["disabled", "Disabled: Lookup"],
    ["closed", "No longer waiting: Lookup"],
  ])("records a %s request on one line", (status, text) => {
    const view = render(<ToolApprovalCard approval={approval(status)} />);
    expect(view.getByText(text)).toBeTruthy();
    expect(view.queryByText("Approve once")).toBeNull();
  });

  it.each<[string, ApprovalDecision, string, string, ApprovalStatus]>([
    [
      "Approve for this chat",
      "approve_session",
      "APPROVED",
      "SESSION_GRANT",
      "approvedForSession",
    ],
    ["Reject", "reject", "REJECTED", "USER", "rejected"],
  ])(
    "%s posts %s and records the %s (%s) decision",
    async (button, decision, serverDecision, decidedVia, status) => {
      postMock.mockResolvedValue({
        decision: serverDecision,
        decided_via: decidedVia,
      });
      const view = render(<ToolApprovalCard approval={approval()} />);

      fireEvent.press(view.getByText(button));

      await waitFor(() =>
        expect(useToolApprovalUi.getState().localStatuses.get("a1")).toBe(
          status,
        ),
      );
      expect(postMock).toHaveBeenCalledWith("a1", decision);
    },
  );

  it.each([404, 409])(
    "closes the request when the server answers %i",
    async (statusCode) => {
      postMock.mockRejectedValue(new ApiError({ status: statusCode }));
      const view = render(<ToolApprovalCard approval={approval()} />);

      fireEvent.press(view.getByText("Approve once"));

      await waitFor(() =>
        expect(useToolApprovalUi.getState().localStatuses.get("a1")).toBe(
          "closed",
        ),
      );
      expect(view.queryByText(/Could not submit/)).toBeNull();
    },
  );

  it("keeps the request actionable after another failure", async () => {
    jest.spyOn(console, "warn").mockImplementation(() => {});
    postMock.mockRejectedValue(new ApiError({ status: 500 }));
    const view = render(<ToolApprovalCard approval={approval()} />);

    fireEvent.press(view.getByText("Reject"));

    expect(
      await view.findByText("Could not submit your decision. Try again."),
    ).toBeTruthy();
    expect(useToolApprovalUi.getState().localStatuses.has("a1")).toBe(false);
    expect(
      view.getByLabelText("Reject this action").props.accessibilityState
        .disabled,
    ).toBe(false);
  });
});

describe("ToolApprovalCard continuation", () => {
  const recoverMock = recoverChatSession as unknown as Mock<
    typeof recoverChatSession
  >;
  const pausedStop: Packet = {
    placement: { turn_index: 0 },
    obj: { type: PacketType.STOP, stop_reason: StopReason.AWAITING_APPROVAL },
  };

  function openPausedResponse(requests: ToolApprovalRequest[]) {
    const node: Message = {
      nodeId: 2,
      messageId: 2,
      parentNodeId: 1,
      type: "assistant",
      message: "",
      files: [],
      packets: [
        ...requests.map((obj) => ({ placement: { turn_index: 0 }, obj })),
        pausedStop,
      ],
    };
    useChatSessionStore.setState({
      currentSessionId: "s",
      sessions: new Map(),
    });
    useChatSessionStore.getState().hydrateSession("s", new Map([[2, node]]));
  }

  beforeEach(() => {
    jest.clearAllMocks();
    useToolApprovalUi.setState({ localStatuses: new Map(), nudgeSeq: 0 });
    postMock.mockResolvedValue({ decision: "APPROVED", decided_via: "USER" });
  });

  it("follows the continuation once no request of the paused response waits", async () => {
    openPausedResponse([request]);
    const view = render(<ToolApprovalCard approval={approval()} />);

    fireEvent.press(view.getByText("Approve once"));

    await waitFor(() => expect(recoverMock).toHaveBeenCalled());
    expect(recoverMock.mock.calls[0]?.slice(0, 2)).toEqual(["s", null]);
    expect(useChatSessionStore.getState().sessions.get("s")?.chatState).toBe(
      "settling",
    );
  });

  it("waits while another request of the response still waits", async () => {
    openPausedResponse([request, { ...request, approval_id: "a2" }]);
    const view = render(<ToolApprovalCard approval={approval()} />);

    fireEvent.press(view.getByText("Approve once"));

    await waitFor(() =>
      expect(useToolApprovalUi.getState().localStatuses.get("a1")).toBe(
        "approved",
      ),
    );
    expect(recoverMock).not.toHaveBeenCalled();
  });
});

describe("MessageRow approvals", () => {
  beforeEach(() => {
    useToolApprovalUi.setState({ localStatuses: new Map(), nudgeSeq: 0 });
  });

  function assistant(packets: Packet[]): Message {
    return {
      nodeId: 2,
      messageId: 2,
      parentNodeId: 1,
      type: "assistant",
      message: "",
      files: [],
      packets,
    };
  }

  const start: Packet = {
    placement: { turn_index: 0 },
    obj: {
      type: PacketType.CUSTOM_TOOL_START,
      tool_name: "lookup",
      display_name: "Lookup",
    },
  } as Packet;
  const requestPacket: Packet = { placement: { turn_index: 0 }, obj: request };

  it("shows the waiting card in the response", () => {
    const view = render(
      <MessageRow node={assistant([start, requestPacket])} agent={null} />,
    );
    expect(view.getByText("Approval requested: Lookup")).toBeTruthy();
  });

  it("shows the server outcome over the local decision", () => {
    useToolApprovalUi.setState({
      localStatuses: new Map([["a1", "approved"]]),
    });
    const view = render(
      <MessageRow
        node={assistant([
          start,
          requestPacket,
          {
            placement: { turn_index: 0 },
            obj: {
              type: PacketType.TOOL_APPROVAL_RESOLVED,
              approval_id: "a1",
              outcome: "rejected",
            },
          },
        ])}
        agent={null}
      />,
    );
    expect(view.getByText("Not approved: Lookup")).toBeTruthy();
  });
});
