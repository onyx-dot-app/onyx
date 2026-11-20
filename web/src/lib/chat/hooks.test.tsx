import { renderHook, waitFor } from "@testing-library/react";
import {
  Packet,
  PacketType,
  ToolApprovalRequest,
} from "@/app/app/services/streamingModels";
import {
  useChatSessionQueue,
  usePublishedFiles,
  useSendChatMessageFromURL,
  useToolRequests,
} from "@/lib/chat/hooks";
import type { Message } from "@/app/app/types";
import type { ToolConfigurationHandle } from "@/lib/tools/hooks";
import { SWR_KEYS } from "@/lib/swr-keys";
import { useToolRequestUi } from "@/lib/chat/toolApprovals";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import { refreshChatSession } from "@/lib/chat/settleChatSession";

jest.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));
jest.mock("@/lib/chat/settleChatSession", () => ({
  ...jest.requireActual("@/lib/chat/settleChatSession"),
  refreshChatSession: jest.fn(async () => {}),
}));
jest.mock("@opal/navigation", () => ({
  ...jest.requireActual("@opal/navigation"),
  useNavigation: () => ({ go: jest.fn() }),
  useSearchParams: () =>
    new URLSearchParams({
      "user-prompt": "hello",
      "send-on-load": "true",
      tags: "eng",
    }),
}));
jest.mock("@/lib/projects/providers", () => ({
  useProjectsContext: () => ({ currentMessageFiles: [] }),
}));
jest.mock("@/lib/connectors/hooks", () => ({
  useAvailableSources: () => ({
    availableSources: [],
    isLoading: false,
    settled: true,
    error: undefined,
  }),
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

function question(questionRequestId: string, turnIndex: number): Packet {
  return {
    placement: { turn_index: turnIndex, tab_index: 0 },
    obj: {
      type: PacketType.TOOL_QUESTION_REQUEST,
      question_request_id: questionRequestId,
      tool_call_id: `call-${questionRequestId}`,
      questions: [
        {
          id: "scope",
          header: "Scope",
          question: "Which scope?",
          options: [
            { label: "All", description: "Every file." },
            { label: "Some", description: "Some files." },
          ],
        },
      ],
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
  useToolRequestUi.setState({
    localStatuses: new Map(),
    localAnswers: new Map(),
    nudge: null,
  })
);

describe("useToolRequests", () => {
  it("keeps records of decided requests and leaves waiting ones out", () => {
    const first = request("first", 1);
    const packets = [first, request("second", 2), resolved("first", 1)];

    const { result } = renderHook(() => useToolRequests(packets));

    expect(result.current).toEqual({
      records: [
        {
          kind: "approval",
          turnIndex: 1,
          request: requestObj(first),
          status: "approved",
        },
      ],
      awaiting: "approval",
    });
  });

  it("follows packets appended to the same array", () => {
    const packets: Packet[] = [request("first", 1)];
    const { result, rerender } = renderHook(() => useToolRequests(packets));
    expect(result.current.records).toEqual([]);

    // Streams append to the array they already passed.
    packets.push(resolved("first", 1));
    rerender();

    expect(result.current.records[0]?.status).toBe("approved");
    expect(result.current.awaiting).toBeNull();
  });

  it("does not wait on a background agent's request", () => {
    const packets = [request("agent", 1, "Researcher")];

    const { result } = renderHook(() => useToolRequests(packets));

    expect(result.current).toEqual({ records: [], awaiting: null });
  });

  it("waits for answers, then records how the user answered", () => {
    const packets: Packet[] = [question("q", 1)];
    const { result, rerender } = renderHook(() => useToolRequests(packets));
    expect(result.current).toEqual({ records: [], awaiting: "answer" });

    packets.push({
      placement: { turn_index: 1, tab_index: 0 },
      obj: {
        type: PacketType.TOOL_QUESTION_RESOLVED,
        question_request_id: "q",
        outcome: "answered",
        answered_via: "message",
        answers: null,
        message: "Only the docs folder",
      },
    });
    rerender();

    expect(result.current.awaiting).toBeNull();
    expect(result.current.records).toMatchObject([
      {
        kind: "question",
        turnIndex: 1,
        status: {
          kind: "answered",
          answers: null,
          message: "Only the docs folder",
        },
      },
    ]);
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

describe("useSendChatMessageFromURL", () => {
  const toolConfiguration: ToolConfigurationHandle = {
    stateOf: () => null,
    setToolState: jest.fn(),
    toggleToolState: jest.fn(),
    clearPreferredTool: jest.fn(),
    preferredToolId: null,
    preferredAction: null,
    disabledToolIds: [],
    isIntegrationEnabled: () => true,
    setIntegrationEnabled: jest.fn(),
    allowed: null,
    ready: true,
    optionsLoaded: true,
    filters: {
      selectedSources: null,
      documentSets: [],
      tags: [],
      timeRange: null,
    },
    setFilters: jest.fn(),
    handOffTo: jest.fn(),
    handOffToNewChatWith: jest.fn(),
  };

  test("a send-on-load query naming tags waits for them and applies them", async () => {
    const fetchMock = jest.fn(async (input: RequestInfo | URL) => {
      const body =
        String(input) === SWR_KEYS.tags
          ? { tags: [{ tag_key: "team", tag_value: "eng", source: "web" }] }
          : [];
      return new Response(JSON.stringify(body), { status: 200 });
    });
    global.fetch = fetchMock;
    const onSubmit = jest.fn();

    renderHook(() =>
      useSendChatMessageFromURL({
        onSubmit,
        deepResearch: false,
        toolConfiguration,
      })
    );

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    const requested = fetchMock.mock.calls.map(([input]) => String(input));
    expect(requested).toContain(SWR_KEYS.tags);
    expect(requested).not.toContain(SWR_KEYS.documentSets);
    const update = jest.mocked(toolConfiguration.setFilters).mock.calls[0]![0];
    expect(
      update(toolConfiguration.filters).tags.map((tag) => tag.tag_value)
    ).toEqual(["eng"]);
  });
});

describe("usePublishedFiles", () => {
  function answer(packets: Packet[]): Message {
    return {
      nodeId: 2,
      messageId: 2,
      type: "assistant",
      message: "",
      files: [],
      packets,
      toolCall: null,
      parentNodeId: null,
    };
  }

  function setAnswer(packets: Packet[]) {
    useChatSessionStore
      .getState()
      .updateSessionMessageTree(
        "files-session",
        new Map([[2, answer(packets)]])
      );
  }

  const publishEnd: Packet = {
    placement: { turn_index: 0, tab_index: 0 },
    obj: {
      type: PacketType.PUBLISH_FILES_END,
      files: [
        {
          file_id: "file-1",
          name: "report.md",
          title: null,
          path: "/w/report.md",
          display_path: "/w/report.md",
          size: 10,
          mime_type: "text/markdown",
        },
      ],
      error: null,
    },
  };

  it("keeps the same files and publish index until a packet publishes a file", () => {
    useChatSessionStore.setState({
      sessions: new Map(),
      currentSessionId: "files-session",
    });
    useChatSessionStore.getState().createSession("files-session");
    setAnswer([publishEnd]);
    const { result, rerender } = renderHook(() => usePublishedFiles("current"));
    const first = result.current;
    expect(first.files.map((file) => file.file_id)).toEqual(["file-1"]);
    expect([...first.publishIndex]).toEqual([["file-1", 0]]);

    // A streamed answer delta replaces the packet array.
    setAnswer([
      publishEnd,
      {
        placement: { turn_index: 1, tab_index: 0 },
        obj: { type: PacketType.MESSAGE_DELTA, content: "Done" },
      },
    ]);
    rerender();
    expect(result.current.files).toBe(first.files);
    expect(result.current.publishIndex).toBe(first.publishIndex);
  });
});
