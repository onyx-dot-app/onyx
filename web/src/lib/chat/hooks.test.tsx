import { renderHook, waitFor } from "@testing-library/react";
import {
  Packet,
  PacketType,
  ToolApprovalRequest,
} from "@/app/app/services/streamingModels";
import { useChatSessionQueue, useToolApprovals } from "@/lib/chat/hooks";
import { useToolApprovalUi } from "@/lib/chat/toolApprovals";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import { refreshChatSession } from "@/lib/chat/settleChatSession";

jest.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));
jest.mock("@/lib/chat/settleChatSession", () => ({
  ...jest.requireActual("@/lib/chat/settleChatSession"),
  refreshChatSession: jest.fn(async () => {}),
}));

function request(
  approvalId: string,
  turnIndex: number,
  agentName: string | null = null
): Packet {
  return {
    placement: { turn_index: turnIndex, tab_index: 0 },
    obj: {
      type: PacketType.TOOL_APPROVAL_REQUEST,
      approval_id: approvalId,
      tool_call_id: `call-${approvalId}`,
      tool_name: "mcp__3__github__create_issue",
      display_name: "Create issue",
      arguments: { title: "Bug" },
      agent_name: agentName,
    },
  };
}

function resolved(approvalId: string, turnIndex: number): Packet {
  return {
    placement: { turn_index: turnIndex, tab_index: 0 },
    obj: {
      type: PacketType.TOOL_APPROVAL_RESOLVED,
      approval_id: approvalId,
      outcome: "approved",
    },
  };
}

function requestObj(packet: Packet): ToolApprovalRequest {
  if (packet.obj.type !== PacketType.TOOL_APPROVAL_REQUEST) {
    throw new Error("not a request");
  }
  return packet.obj;
}

beforeEach(() =>
  useToolApprovalUi.setState({ localStatuses: new Map(), nudge: null })
);

describe("useToolApprovals", () => {
  it("keeps records of decided requests and leaves waiting ones out", () => {
    const first = request("first", 1);
    const packets = [first, request("second", 2), resolved("first", 1)];

    const { result } = renderHook(() => useToolApprovals(packets));

    expect(result.current).toEqual({
      records: [
        { turnIndex: 1, request: requestObj(first), status: "approved" },
      ],
      awaitingApproval: true,
    });
  });

  it("follows packets appended to the same array", () => {
    const packets: Packet[] = [request("first", 1)];
    const { result, rerender } = renderHook(() => useToolApprovals(packets));
    expect(result.current.records).toEqual([]);

    // Streams append to the array they already passed.
    packets.push(resolved("first", 1));
    rerender();

    expect(result.current.records[0]?.status).toBe("approved");
    expect(result.current.awaitingApproval).toBe(false);
  });

  it("does not wait on a background agent's request", () => {
    const packets = [request("agent", 1, "Researcher")];

    const { result } = renderHook(() => useToolApprovals(packets));

    expect(result.current).toEqual({ records: [], awaitingApproval: false });
  });
});

describe("useChatSessionQueue", () => {
  beforeEach(() => jest.mocked(refreshChatSession).mockClear());
  afterEach(() => jest.restoreAllMocks());

  function serveStatus(approvalsVersion: string) {
    return jest.spyOn(global, "fetch").mockImplementation(
      async () =>
        new Response(
          JSON.stringify({
            is_processing: false,
            current_stream: null,
            has_startable_input: false,
            has_active_subagents: false,
            latest_response_id: null,
            approvals_version: approvalsVersion,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        )
    );
  }

  function startChat(sessionId: string) {
    useChatSessionStore.setState({
      sessions: new Map(),
      currentSessionId: sessionId,
    });
    useChatSessionStore
      .getState()
      .createSession(sessionId, { chatState: "input" });
  }

  it("does not refresh a started chat that has no approval request", async () => {
    startChat("clean-session");
    const fetchMock = serveStatus("");

    renderHook(() => useChatSessionQueue(true));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(refreshChatSession).not.toHaveBeenCalled();
  });

  it("refreshes a started chat whose first status read already holds a request", async () => {
    startChat("asked-session");
    serveStatus("1/0/2026-11-15 05:00:00/None");

    renderHook(() => useChatSessionQueue(true));

    await waitFor(() =>
      expect(refreshChatSession).toHaveBeenCalledWith(
        "asked-session",
        expect.any(String)
      )
    );
  });

  it("refreshes an incognito chat whose approvals changed, without its server queue", async () => {
    useChatSessionStore.setState({
      sessions: new Map(),
      currentSessionId: "incognito-session",
    });
    useChatSessionStore.getState().createSession("incognito-session", {
      incognito: true,
      chatState: "input",
      approvalsVersion: "1",
    });
    const fetchMock = jest.spyOn(global, "fetch").mockImplementation(
      async () =>
        new Response(
          JSON.stringify({
            is_processing: false,
            current_stream: null,
            has_startable_input: false,
            has_active_subagents: true,
            latest_response_id: null,
            approvals_version: "2",
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        )
    );

    renderHook(() => useChatSessionQueue(false));

    await waitFor(() =>
      expect(refreshChatSession).toHaveBeenCalledWith(
        "incognito-session",
        expect.any(String)
      )
    );
    // Only the status is read; an incognito chat has no pending list.
    expect(
      fetchMock.mock.calls.every(([input]) => String(input).endsWith("/status"))
    ).toBe(true);
  });
});
