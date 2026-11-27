import { act, renderHook, waitFor } from "@testing-library/react";
import { SWRConfig } from "swr";
import { SUBMIT_MESSAGE_TYPES } from "@/lib/extension/constants";
import {
  Packet,
  PacketType,
  StopReason,
  ToolApprovalRequest,
} from "@/app/app/services/streamingModels";
import {
  useChatSessionQueue,
  useChatSessionStatus,
  useChatSubagents,
  useJumpToLatestReason,
  useOpenArtifactFromUrl,
  usePublishedFiles,
  useSendChatMessageFromURL,
  useToolRequests,
} from "@/lib/chat/hooks";
import type { Message } from "@/app/app/types";
import type { ToolConfigurationHandle } from "@/lib/tools/hooks";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  ToolRequestDeciderContext,
  useToolRequestUi,
} from "@/lib/chat/toolApprovals";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import { endedRunStatus } from "@/lib/chat/runStatus";
import { refreshChatSession } from "@/lib/chat/settleChatSession";
import type { ChatArtifactFile } from "@/lib/chat/publishedFiles";
import { SEARCH_PARAM_NAMES } from "@/app/app/services/searchParams";

jest.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));
jest.mock("@/lib/chat/settleChatSession", () => ({
  ...jest.requireActual("@/lib/chat/settleChatSession"),
  refreshChatSession: jest.fn(async () => {}),
}));
const SEND_ON_LOAD_PARAMS = new URLSearchParams({
  "user-prompt": "hello",
  "send-on-load": "true",
  tags: "eng",
});
let mockSearchParams = SEND_ON_LOAD_PARAMS;
jest.mock("@opal/navigation", () => ({
  ...jest.requireActual("@opal/navigation"),
  useNavigation: () => ({ go: jest.fn() }),
  useSearchParams: () => mockSearchParams,
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
          multi_select: false,
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

describe("useToolRequests in a chat that the viewer only reads", () => {
  function readOnly({ children }: { children: React.ReactNode }) {
    return (
      <ToolRequestDeciderContext.Provider value={false}>
        {children}
      </ToolRequestDeciderContext.Provider>
    );
  }

  it("waits for the owner's approval, not the viewer's", () => {
    const packets = [request("a", 1)];

    const { result } = renderHook(() => useToolRequests(packets), {
      wrapper: readOnly,
    });

    expect(result.current.awaiting).toBe("ownerApproval");
  });

  it("waits for the owner's answer, not the viewer's", () => {
    const packets = [question("q", 1)];

    const { result } = renderHook(() => useToolRequests(packets), {
      wrapper: readOnly,
    });

    expect(result.current.awaiting).toBe("ownerAnswer");
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

  it("polls the status while a shown request waits, so a decision made elsewhere arrives", async () => {
    startChat("waiting-session");
    const node = (
      nodeId: number,
      type: Message["type"],
      parentNodeId: number | null
    ): Message => ({
      nodeId,
      messageId: nodeId,
      type,
      message: "",
      files: [],
      packets: type === "assistant" ? [request("a", 1)] : [],
      toolCall: null,
      parentNodeId,
      latestChildNodeId: type === "user" ? 2 : null,
    });
    useChatSessionStore.getState().updateSessionMessageTree(
      "waiting-session",
      new Map([
        [1, node(1, "user", null)],
        [2, node(2, "assistant", 1)],
      ])
    );
    const fetchMock = serveStatus("");
    const statusReads = () =>
      fetchMock.mock.calls.filter(([input]) =>
        String(input).endsWith("/status")
      ).length;

    renderHook(() => useChatSessionQueue(true));

    await waitFor(() => expect(statusReads()).toBeGreaterThanOrEqual(2), {
      timeout: 5000,
    });
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

describe("useChatSessionStatus", () => {
  afterEach(() => jest.restoreAllMocks());

  function serveIdleStatus() {
    return jest.spyOn(global, "fetch").mockImplementation(
      async () =>
        new Response(
          JSON.stringify({
            is_processing: false,
            current_stream: null,
            has_startable_input: false,
            has_active_subagents: false,
            latest_response_id: null,
            approvals_version: "",
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        )
    );
  }

  function statusReads(fetchMock: jest.SpyInstance): number {
    return fetchMock.mock.calls.filter(([input]) =>
      String(input).endsWith("/status")
    ).length;
  }

  function startChat(
    sessionId: string,
    chatState: "input" | "streaming",
    packets: Packet[]
  ) {
    useChatSessionStore.setState({
      sessions: new Map(),
      currentSessionId: sessionId,
    });
    useChatSessionStore.getState().createSession(sessionId, { chatState });
    const user: Message = {
      nodeId: 1,
      messageId: 1,
      type: "user",
      message: "",
      files: [],
      packets: [],
      toolCall: null,
      parentNodeId: null,
      latestChildNodeId: 2,
    };
    useChatSessionStore.getState().updateSessionMessageTree(
      sessionId,
      new Map([
        [1, user],
        [
          2,
          {
            ...user,
            nodeId: 2,
            messageId: 2,
            type: "assistant",
            packets,
            parentNodeId: 1,
            latestChildNodeId: null,
          },
        ],
      ])
    );
  }

  // Each hook gets its own SWR cache, so each reads the status itself.
  function fresh({ children }: { children: React.ReactNode }) {
    return (
      <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
        {children}
      </SWRConfig>
    );
  }

  it("reads an idle chat's status once", async () => {
    startChat("idle-session", "input", []);
    const fetchMock = serveIdleStatus();

    renderHook(() => useChatSessionStatus("idle-session"), { wrapper: fresh });

    await waitFor(() => expect(statusReads(fetchMock)).toBe(1));
    await new Promise((resolve) => setTimeout(resolve, 2500));
    expect(statusReads(fetchMock)).toBe(1);
  });

  it("polls while a reply streams", async () => {
    startChat("streaming-session", "streaming", []);
    const fetchMock = serveIdleStatus();

    renderHook(() => useChatSessionStatus("streaming-session"), {
      wrapper: fresh,
    });

    await waitFor(() => expect(statusReads(fetchMock)).toBeGreaterThan(1), {
      timeout: 5000,
    });
  });

  it("keeps polling while its host renders more often than it polls", async () => {
    startChat("busy-session", "input", []);
    const fetchMock = jest.spyOn(global, "fetch").mockImplementation(
      async () =>
        new Response(
          JSON.stringify({
            is_processing: false,
            current_stream: null,
            has_startable_input: false,
            has_active_subagents: true,
            latest_response_id: null,
            approvals_version: "",
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        )
    );

    const { rerender } = renderHook(
      () => useChatSessionStatus("busy-session"),
      {
        wrapper: fresh,
      }
    );
    await waitFor(() => expect(statusReads(fetchMock)).toBe(1));
    const renders = setInterval(() => rerender(), 500);
    try {
      await waitFor(() => expect(statusReads(fetchMock)).toBeGreaterThan(1), {
        timeout: 5000,
      });
    } finally {
      clearInterval(renders);
    }
  });

  it("polls for the agents list while a shown request waits, as for the queue", async () => {
    startChat("agents-session", "input", [request("a", 1)]);
    const fetchMock = serveIdleStatus();

    renderHook(() => useChatSubagents("agents-session"), { wrapper: fresh });

    await waitFor(() => expect(statusReads(fetchMock)).toBeGreaterThan(1), {
      timeout: 5000,
    });
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

  test("only the embedding extension, not a frame inside the page, can send a prompt", async () => {
    mockSearchParams = new URLSearchParams();
    global.fetch = jest.fn(async () => new Response("[]", { status: 200 }));
    // The extension embeds the page: its window is the page's parent
    const extension = document.createElement("iframe");
    // An HTML file preview is a frame inside the page
    const preview = document.createElement("iframe");
    document.body.append(extension, preview);
    const parent = Object.getOwnPropertyDescriptor(window, "parent");
    Object.defineProperty(window, "parent", {
      configurable: true,
      value: extension.contentWindow,
    });
    const onSubmit = jest.fn();
    function send(source: Window | null, prompt: string) {
      window.dispatchEvent(
        new MessageEvent("message", {
          source,
          origin: "chrome-extension://abc",
          data: {
            type: SUBMIT_MESSAGE_TYPES.PAGE_CHANGE,
            href: `${window.location.origin}${window.location.pathname}?user-prompt=${prompt}&send-on-load=true`,
          },
        })
      );
    }
    try {
      renderHook(() =>
        useSendChatMessageFromURL({
          onSubmit,
          deepResearch: false,
          toolConfiguration,
        })
      );

      await act(async () => send(preview.contentWindow, "leak"));
      await act(async () => send(extension.contentWindow, "hello"));

      await waitFor(() => expect(onSubmit).toHaveBeenCalled());
      expect(onSubmit.mock.calls.map(([message]) => message.message)).toEqual([
        "hello",
      ]);
    } finally {
      if (parent) Object.defineProperty(window, "parent", parent);
      extension.remove();
      preview.remove();
    }
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
          artifact_id: "artifact-1",
          version: 1,
          thumbnail_file_id: null,
          chat_id: null,
        },
      ],
      error: null,
    },
  };

  it("keeps the same files until a packet publishes a file", () => {
    useChatSessionStore.setState({
      sessions: new Map(),
      currentSessionId: "files-session",
    });
    useChatSessionStore.getState().createSession("files-session");
    setAnswer([publishEnd]);
    const { result, rerender } = renderHook(() => usePublishedFiles("current"));
    const first = result.current;
    expect(first.map((file) => file.file_id)).toEqual(["file-1"]);

    // A streamed answer delta replaces the packet array.
    setAnswer([
      publishEnd,
      {
        placement: { turn_index: 1, tab_index: 0 },
        obj: { type: PacketType.MESSAGE_DELTA, content: "Done" },
      },
    ]);
    rerender();
    expect(result.current).toBe(first);
  });
});

describe("useJumpToLatestReason", () => {
  const SESSION = "jump-session";

  function setReply(packets: Packet[]) {
    const node = (
      nodeId: number,
      type: Message["type"],
      parentNodeId: number | null
    ): Message => ({
      nodeId,
      messageId: nodeId,
      type,
      message: "",
      files: [],
      packets: type === "assistant" ? packets : [],
      toolCall: null,
      parentNodeId,
      latestChildNodeId: type === "user" ? 2 : null,
    });
    useChatSessionStore.getState().updateSessionMessageTree(
      SESSION,
      new Map([
        [1, node(1, "user", null)],
        [2, node(2, "assistant", 1)],
      ])
    );
  }

  const delta = (content: string): Packet => ({
    placement: { turn_index: 0, tab_index: 0 },
    obj: { type: PacketType.MESSAGE_DELTA, content },
  });

  beforeEach(() => {
    useChatSessionStore.setState({
      sessions: new Map(),
      currentSessionId: SESSION,
    });
    useChatSessionStore
      .getState()
      .createSession(SESSION, { chatState: "streaming" });
    setReply([delta("Hello")]);
  });

  it("names nothing while the button is hidden", () => {
    setReply([request("a", 1)]);
    const { result } = renderHook(() => useJumpToLatestReason(false));
    expect(result.current).toBeNull();
  });

  it("names a waiting approval until this client decides it", () => {
    setReply([request("a", 1), question("q", 2)]);
    const { result, rerender } = renderHook(() => useJumpToLatestReason(true));
    expect(result.current).toBe("approval");

    useToolRequestUi.getState().recordStatus("a", "approved");
    rerender();
    expect(result.current).toBe("question");
  });

  it("names a new answer once the run ends with output after the scroll", () => {
    const { result, rerender } = renderHook(
      ({ visible }) => useJumpToLatestReason(visible),
      { initialProps: { visible: true } }
    );
    expect(result.current).toBeNull();

    setReply([delta("Hello"), delta(" world")]);
    rerender({ visible: true });
    // Still streaming: the plain button stays.
    expect(result.current).toBeNull();

    useChatSessionStore.getState().updateChatState(SESSION, "input");
    rerender({ visible: true });
    expect(result.current).toBe("newAnswer");

    // Back at the end, then away again: nothing new since.
    rerender({ visible: false });
    rerender({ visible: true });
    expect(result.current).toBeNull();
  });

  it("does not call a final stop packet a new answer", () => {
    const { result } = renderHook(() => useJumpToLatestReason(true));
    act(() => {
      setReply([
        delta("Hello"),
        {
          placement: { turn_index: 0, tab_index: 0 },
          obj: { type: PacketType.STOP },
        },
      ]);
      useChatSessionStore.getState().updateChatState(SESSION, "input");
    });
    expect(result.current).toBeNull();
  });

  it.each([
    [StopReason.TIMED_OUT, "failed"],
    [StopReason.USER_CANCELLED, null],
    [StopReason.FINISHED, "done"],
  ])("records the terminal status for %s", (stop_reason, expected) => {
    setReply([
      delta("Hello"),
      {
        placement: { turn_index: 0, tab_index: 0 },
        obj: { type: PacketType.STOP, stop_reason },
      },
    ]);
    useChatSessionStore.getState().updateChatState(SESSION, "input");
    const session = useChatSessionStore.getState().sessions.get(SESSION);
    if (!session) throw new Error("Expected a chat session");
    expect(endedRunStatus(session)).toBe(expected);
  });

  it("keeps a rejected local send out of the followed run's status", () => {
    setReply([delta("Hello")]);
    const store = useChatSessionStore.getState();
    store.updateChatState(SESSION, "input");
    store.setUncaughtError(SESSION, {
      error: "A run is already active",
      affectsRunStatus: false,
    });
    const session = useChatSessionStore.getState().sessions.get(SESSION);
    if (!session) throw new Error("Expected a chat session");
    expect(endedRunStatus(session)).toBe("done");
  });

  it("names no new answer for output that loads into an idle chat", () => {
    useChatSessionStore.getState().updateChatState(SESSION, "input");
    const { result, rerender } = renderHook(() => useJumpToLatestReason(true));

    // An opened chat's history arrives, or its settled run is fetched again.
    act(() => setReply([delta("Hello"), delta(" world")]));
    rerender();
    expect(result.current).toBeNull();
  });
});

describe("useOpenArtifactFromUrl", () => {
  const ARTIFACT_ID = "5b1d2c3e-0000-4000-8000-000000000000";
  const FILE: ChatArtifactFile = {
    file_id: "report-v1",
    name: "report.md",
    title: null,
    path: "/outputs/report.md",
    display_path: "report.md",
    size: 1,
    mime_type: "text/markdown",
    artifact_id: ARTIFACT_ID,
    version: 1,
    thumbnail_file_id: null,
    chat_id: "chat",
    access: "owner",
  };

  beforeEach(() => {
    jest
      .spyOn(global, "fetch")
      .mockImplementation(
        async () => new Response(JSON.stringify(FILE), { status: 200 })
      );
  });

  afterEach(() => {
    mockSearchParams = SEND_ON_LOAD_PARAMS;
    jest.restoreAllMocks();
  });

  test.each([
    ["names a version opens it pinned", "1", true],
    ["names no version follows the newest", null, false],
  ])("a URL that %s", async (_, version, pinned) => {
    mockSearchParams = new URLSearchParams({
      [SEARCH_PARAM_NAMES.ARTIFACT_ID]: ARTIFACT_ID,
      ...(version ? { [SEARCH_PARAM_NAMES.ARTIFACT_VERSION]: version } : {}),
    });
    const openFile = jest.fn();
    renderHook(() => useOpenArtifactFromUrl("chat", openFile));
    await waitFor(() => expect(openFile).toHaveBeenCalledWith(FILE, pinned));
  });

  test("a cached response of an earlier visit waits for the newest version", async () => {
    mockSearchParams = new URLSearchParams({
      [SEARCH_PARAM_NAMES.ARTIFACT_ID]: ARTIFACT_ID,
    });
    const newer = { ...FILE, file_id: "report-v2", version: 2 };
    jest
      .spyOn(global, "fetch")
      .mockImplementation(
        async () => new Response(JSON.stringify(newer), { status: 200 })
      );
    const cache = new Map([
      [SWR_KEYS.chatArtifact(ARTIFACT_ID, null), { data: FILE }],
    ]);
    const openFile = jest.fn();
    renderHook(() => useOpenArtifactFromUrl("chat", openFile), {
      wrapper: ({ children }) => (
        <SWRConfig value={{ provider: () => cache }}>{children}</SWRConfig>
      ),
    });
    await waitFor(() => expect(openFile).toHaveBeenCalledWith(newer, false));
    expect(openFile).toHaveBeenCalledTimes(1);
  });

  test("a cached response of an earlier visit stays shut when the reload fails", async () => {
    mockSearchParams = new URLSearchParams({
      [SEARCH_PARAM_NAMES.ARTIFACT_ID]: ARTIFACT_ID,
    });
    jest.spyOn(global, "fetch").mockImplementation(
      async () =>
        new Response(JSON.stringify({ detail: "Not found" }), {
          status: 404,
        })
    );
    const cache = new Map([
      [SWR_KEYS.chatArtifact(ARTIFACT_ID, null), { data: FILE }],
    ]);
    const openFile = jest.fn();
    renderHook(() => useOpenArtifactFromUrl("chat", openFile), {
      wrapper: ({ children }) => (
        <SWRConfig value={{ provider: () => cache, shouldRetryOnError: false }}>
          {children}
        </SWRConfig>
      ),
    });
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(openFile).not.toHaveBeenCalled();
  });

  test.each([
    ["../x", null],
    [ARTIFACT_ID, "x"],
    [ARTIFACT_ID, "1.5"],
  ])(
    "an artifact %s at version %s that no link names makes no request",
    async (artifactId, version) => {
      mockSearchParams = new URLSearchParams({
        [SEARCH_PARAM_NAMES.ARTIFACT_ID]: artifactId,
        ...(version ? { [SEARCH_PARAM_NAMES.ARTIFACT_VERSION]: version } : {}),
      });
      const openFile = jest.fn();
      renderHook(() => useOpenArtifactFromUrl("chat", openFile));
      await act(async () => {});
      expect(global.fetch).not.toHaveBeenCalled();
      expect(openFile).not.toHaveBeenCalled();
    }
  );
});
