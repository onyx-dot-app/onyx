import {
  ChatSessionSharedStatus,
  type BackendMessage,
  type Message,
} from "@/app/app/types";
import { processRawChatHistory } from "@/app/app/services/lib";
import {
  act,
  render,
  screen,
  setupUser,
  deferred,
  waitFor,
} from "@tests/setup/test-utils";
import AppInputBar, { AppInputBarProps } from "@/sections/input/AppInputBar";
import {
  waitForChatResponseEnd,
  fetchSettledChatSession,
} from "@/lib/chat/sessionReadiness";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";

Element.prototype.scrollIntoView = jest.fn();

let mockSearchMode = false;
let mockIncognito = false;
let pending: import("@/lib/chat/types").PendingChatMessage[] = [];
const mockRefreshChatSession = jest.fn().mockResolvedValue(undefined);
jest.mock("@/lib/chat/settleChatSession", () => ({
  ...jest.requireActual<typeof import("@/lib/chat/settleChatSession")>(
    "@/lib/chat/settleChatSession"
  ),
  refreshChatSession: (...args: unknown[]) => mockRefreshChatSession(...args),
}));
let requestLog: { method: string; body: string | undefined }[] = [];
let fetchSpy: jest.SpiedFunction<typeof fetch>;

const mockClearDraft = jest.fn();

jest.mock("@/lib/chat/sessionReadiness", () => ({
  waitForChatResponseEnd: jest.fn(),
  fetchSettledChatSession: jest.fn(),
}));
jest.mock("@/app/app/services/lib", () => ({
  processRawChatHistory: jest.fn(() => new Map()),
}));

jest.mock("@/providers/IncognitoProvider", () => ({
  useIncognito: () => ({ incognitoEnabled: mockIncognito }),
}));
jest.mock("@/providers/QueryControllerProvider", () => ({
  useQueryController: () => ({
    state: {
      phase: mockSearchMode ? "search-results" : "idle",
      appMode: "chat",
    },
  }),
}));
jest.mock("@/providers/VoiceModeProvider", () => ({
  useVoiceMode: () => ({ stopTTS: jest.fn() }),
}));
jest.mock("@/hooks/useVoiceStatus", () => ({
  useVoiceStatus: () => ({ sttEnabled: false }),
}));
jest.mock("next/navigation", () => ({
  ...jest.requireActual<typeof import("@tests/setup/mocks/nextNavigation")>(
    "@tests/setup/mocks/nextNavigation"
  ).nextNavigationMock,
  useRouter: () => ({}),
}));
jest.mock("@/lib/navigation/hooks", () => ({
  useAppPosition: () => ({ isNewSession: () => false, chat: () => "session" }),
}));
jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({ appName: "Onyx" }),
}));
jest.mock("@/lib/projects/providers", () => ({
  useProjectsContext: () => ({
    currentMessageFiles: [],
    setCurrentMessageFiles: jest.fn(),
  }),
}));
jest.mock("@/lib/projects/hooks", () => ({
  useProjects: () => ({ isLoading: false }),
  useActiveProject: () => null,
}));
jest.mock("@/lib/connectors/hooks", () => ({
  useAvailableSources: () => ({ isLoading: false }),
}));
jest.mock("@/hooks/usePromptShortcuts", () => ({
  __esModule: true,
  default: () => ({ activePromptShortcuts: [] }),
}));
jest.mock("@/hooks/useDraft", () => ({
  ...jest.requireActual<typeof import("@/hooks/useDraft")>("@/hooks/useDraft"),
  draftKey: () => "draft",
  useDraft: () => ({
    loaded: true,
    draft: undefined,
    save: jest.fn(),
    clear: mockClearDraft,
  }),
}));
jest.mock("@/refresh-components/popovers/FilePickerPopover", () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock("@/lib/tools/components", () => ({ ToolsPopover: () => null }));
jest.mock("@/components/voice/Waveform", () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock("@/sections/cards/FileCard", () => ({ FileCard: () => null }));

function props(chatState: AppInputBarProps["chatState"]): AppInputBarProps {
  return {
    chatState,
    initialMessage: "Keep this draft",
    onSubmit: jest.fn(),
    stopGenerating: jest.fn(),
    handleFileUpload: jest.fn(),
    toggleDeepResearch: jest.fn(),
    deepResearchEnabled: false,
    disabled: false,
    activeAgent: undefined,
    llmManager: { isLoadingProviders: false } as AppInputBarProps["llmManager"],
    toolConfiguration: {} as AppInputBarProps["toolConfiguration"],
  };
}

beforeEach(() => {
  mockSearchMode = false;
  mockIncognito = false;
  requestLog = [];
  pending = [
    {
      id: "queued",
      message: "Queued follow-up",
      delivery: "queue",
      target_response_id: 2,
    },
  ];
  mockRefreshChatSession.mockReset().mockResolvedValue(undefined);
  jest.mocked(waitForChatResponseEnd).mockReset();
  jest.mocked(processRawChatHistory).mockImplementation(() => new Map());
  fetchSpy = jest
    .spyOn(global, "fetch")
    .mockImplementation(async (url, init) => {
      const method = init?.method ?? "GET";
      requestLog.push({
        method,
        body: typeof init?.body === "string" ? init.body : undefined,
      });
      if (method === "POST") {
        const body: {
          message: string;
          delivery: "send" | "queue";
          target_response_id: number;
        } = JSON.parse(String(init?.body));
        const item = { id: `pending-${pending.length}`, ...body };
        pending.push(item);
        return new Response(JSON.stringify(item), { status: 200 });
      }
      if (method === "DELETE") {
        const id = String(url).split("/").at(-1);
        const item = pending.find((message) => message.id === id);
        pending = pending.filter((message) => message.id !== id);
        return new Response(
          JSON.stringify(item ?? { detail: "Already accepted" }),
          { status: item ? 200 : 409 }
        );
      }
      return new Response(JSON.stringify(pending));
    });
  mockClearDraft.mockClear();
  jest.mocked(fetchSettledChatSession).mockResolvedValue({
    chat_session_id: "session",
    description: "Existing chat",
    persona_id: 0,
    persona_name: "Assistant",
    time_created: "2026-10-02T00:00:00Z",
    time_updated: "2026-10-02T00:00:00Z",
    shared_status: ChatSessionSharedStatus.Private,
    current_temperature_override: null,
    current_reasoning_effort_override: null,
    owner_name: null,
    messages: [],
    packets: [],
    is_processing: false,
    current_stream: null,
  });
  useChatSessionStore.setState({ sessions: new Map(), currentSessionId: null });
  const store = useChatSessionStore.getState();
  store.createSession("session");
  store.setCurrentSession("session");
  const history = new Map<number, Message>([
    [
      1,
      {
        nodeId: 1,
        messageId: 1,
        type: "user",
        message: "Question",
        files: [],
        packets: [],
        toolCall: null,
        parentNodeId: null,
        latestChildNodeId: 2,
        childrenNodeIds: [2],
      },
    ],
    [
      2,
      {
        nodeId: 2,
        messageId: 2,
        type: "assistant",
        message: "Answer",
        files: [],
        packets: [],
        toolCall: null,
        parentNodeId: 1,
      },
    ],
  ]);
  store.updateSessionMessageTree("session", history);
});

afterEach(() => fetchSpy.mockRestore());

test("completion checks stay with their sessions across navigation", async () => {
  const user = setupUser();
  const firstIdle = deferred<number | null>();
  const secondIdle = deferred<number | null>();
  jest
    .mocked(waitForChatResponseEnd)
    .mockImplementation((sessionId) =>
      sessionId === "session" ? firstIdle.promise : secondIdle.promise
    );
  const store = useChatSessionStore.getState();
  store.updateChatState("session", "unconfirmed");
  store.createSession("other", { chatState: "unconfirmed" });
  const { rerender } = render(<AppInputBar {...props("unconfirmed")} />);

  await user.click(screen.getByRole("button", { name: /Check again$/ }));
  act(() => store.setCurrentSession("other"));
  rerender(<AppInputBar {...props("unconfirmed")} />);
  expect(screen.getByRole("button", { name: /Check again$/ })).toBeEnabled();
  await user.click(screen.getByRole("button", { name: /Check again$/ }));

  act(() => store.setCurrentSession("session"));
  rerender(<AppInputBar {...props("unconfirmed")} />);
  expect(screen.getByRole("button", { name: /Check again$/ })).toBeDisabled();
  await act(async () => firstIdle.resolve(null));
  act(() => store.setCurrentSession("other"));
  rerender(<AppInputBar {...props("unconfirmed")} />);
  expect(screen.getByRole("button", { name: /Check again$/ })).toBeDisabled();
  await act(async () => secondIdle.resolve(null));
  expect(screen.getByRole("button", { name: /Check again$/ })).toBeEnabled();
});

test("search cannot submit or clear a draft while readiness is unconfirmed", async () => {
  mockSearchMode = true;
  const user = setupUser();
  const inputProps = props("unconfirmed");
  const { container } = render(<AppInputBar {...inputProps} />);
  const send = container.querySelector<HTMLButtonElement>(
    "#onyx-chat-input-send-button"
  );
  expect(send).toBeDisabled();
  if (!send) throw new Error("Search submission button is missing");
  await user.click(send);
  expect(inputProps.onSubmit).not.toHaveBeenCalled();
  expect(mockClearDraft).not.toHaveBeenCalled();
  expect(
    screen.getByRole("textbox", { name: "Message input" })
  ).toHaveTextContent("Keep this draft");
});

test("stopping preserves the draft and queue until completion", async () => {
  const user = setupUser();
  const inputProps = props("cancelling");
  const { rerender } = render(<AppInputBar {...inputProps} />);
  const stopping = screen.getByRole("button", { name: /Stopping…$/ });
  expect(stopping).toBeDisabled();
  const textbox = screen.getByRole("textbox", { name: "Message input" });
  await user.click(textbox);
  await user.keyboard("{Enter}");
  await user.click(stopping);
  expect(textbox).toHaveTextContent("Keep this draft");
  expect(inputProps.onSubmit).not.toHaveBeenCalled();
  expect(pending).toHaveLength(1);

  rerender(<AppInputBar {...inputProps} chatState="input" />);
  expect(inputProps.onSubmit).not.toHaveBeenCalled();
  expect(textbox).toHaveTextContent("Keep this draft");
});

test("unconfirmed completion offers a retry and never submits the draft or queue", async () => {
  const user = setupUser();
  const inputProps = props("unconfirmed");
  render(<AppInputBar {...inputProps} />);
  expect(screen.getByRole("button", { name: /Check again$/ })).toBeEnabled();
  const textbox = screen.getByRole("textbox", { name: "Message input" });
  await user.click(textbox);
  await user.keyboard("{Enter}");
  expect(inputProps.onSubmit).not.toHaveBeenCalled();
  expect(textbox).toHaveTextContent("Keep this draft");
  expect(pending).toHaveLength(1);
});

test("a failed save keeps queued messages paused when manual input is available", () => {
  const inputProps = props("cancelling");
  const { rerender } = render(<AppInputBar {...inputProps} />);
  rerender(<AppInputBar {...inputProps} chatState="input" />);
  expect(inputProps.onSubmit).not.toHaveBeenCalled();
});

test.each([false, true])(
  "retrying completion preserves the draft and paused queue (failed acknowledgement: %s)",
  async (failedAcknowledgement) => {
    const user = setupUser();
    const idle = deferred<number | null>();
    jest.mocked(waitForChatResponseEnd).mockReturnValue(idle.promise);

    const store = useChatSessionStore.getState();
    const sendAcknowledged = failedAcknowledgement
      ? Promise.reject(new TypeError("Connection lost before admission"))
      : undefined;
    void sendAcknowledged?.catch(() => {});
    store.updateSessionData("session", {
      chatState: "unconfirmed",
      sendAcknowledged,
    });
    const inputProps = props("unconfirmed");
    const { rerender } = render(<AppInputBar {...inputProps} />);
    await user.click(screen.getByRole("button", { name: /Check again$/ }));
    expect(waitForChatResponseEnd).toHaveBeenCalledWith("session", undefined);
    expect(screen.getByRole("button", { name: /Check again$/ })).toBeDisabled();
    expect(inputProps.onSubmit).not.toHaveBeenCalled();
    await act(async () => idle.resolve(null));
    expect(
      useChatSessionStore.getState().sessions.get("session")?.chatState
    ).toBe("input");
    rerender(<AppInputBar {...inputProps} chatState="input" />);
    expect(
      screen.getByRole("textbox", { name: "Message input" })
    ).toHaveTextContent("Keep this draft");
    expect(pending).toHaveLength(1);
    expect(inputProps.onSubmit).not.toHaveBeenCalled();
    expect(fetchSettledChatSession).toHaveBeenCalledWith("session");
  }
);

test("a pending readiness check does not disable Stop when streaming resumes", async () => {
  const user = setupUser();
  const reader = deferred<void>();
  const store = useChatSessionStore.getState();
  store.updateSessionData("session", {
    chatState: "unconfirmed",
    readerFinished: reader.promise,
  });
  const inputProps = { ...props("unconfirmed"), initialMessage: "" };
  const { rerender, container } = render(<AppInputBar {...inputProps} />);
  await user.click(screen.getByRole("button", { name: /Check again$/ }));
  act(() => store.updateChatState("session", "streaming"));
  rerender(<AppInputBar {...inputProps} chatState="streaming" />);
  const stop = container.querySelector<HTMLButtonElement>(
    "#onyx-chat-input-send-button"
  );
  expect(stop).toBeEnabled();
  if (!stop) throw new Error("Stop button is missing");
  await user.click(stop);
  expect(inputProps.stopGenerating).toHaveBeenCalledTimes(1);
  await act(async () => reader.resolve());
});

test.each(["{Enter}", "{Control>}{Enter}{/Control}", "{Meta>}{Enter}{/Meta}"])(
  "submits pending input through the server with %s",
  async (keys) => {
    const user = setupUser();
    const inputProps = props("streaming");
    render(<AppInputBar {...inputProps} />);
    const textbox = screen.getByRole("textbox", { name: "Message input" });
    await user.click(textbox);
    await user.keyboard(keys);
    await waitFor(() => expect(pending).toHaveLength(2));
    expect(pending[1]).toMatchObject({
      message: "Keep this draft",
      target_response_id: 2,
      delivery: keys === "{Enter}" ? "queue" : "send",
    });
    expect(inputProps.onSubmit).not.toHaveBeenCalled();
    await waitFor(() => expect(textbox).toHaveTextContent(/^$/));
    expect(await screen.findByText("Keep this draft")).toBeVisible();
  }
);

test("failed queue submission retains the draft and does not add a local message", async () => {
  const user = setupUser();
  fetchSpy.mockImplementation(
    async (_url, init) =>
      new Response(
        JSON.stringify(
          init?.method === "POST"
            ? { detail: "Response has finished" }
            : pending
        ),
        { status: init?.method === "POST" ? 409 : 200 }
      )
  );
  render(<AppInputBar {...props("streaming")} />);
  const textbox = screen.getByRole("textbox", { name: "Message input" });
  await user.click(textbox);
  await user.keyboard("{Enter}");
  expect(textbox).toHaveTextContent("Keep this draft");
  expect(pending).toHaveLength(1);
  expect(mockClearDraft).not.toHaveBeenCalled();
});

test("edit withdraws the message before putting its text in the input", async () => {
  const user = setupUser();
  const deletion = deferred<Response>();
  fetchSpy.mockImplementation(async (_url, init) =>
    init?.method === "DELETE"
      ? deletion.promise
      : new Response(JSON.stringify(pending))
  );
  render(<AppInputBar {...props("streaming")} initialMessage="" />);
  await screen.findByText("Queued follow-up");
  const textbox = screen.getByRole("textbox", { name: "Message input" });
  await user.click(textbox);
  await user.keyboard("{ArrowUp}{Enter}");
  expect(textbox).toHaveTextContent(/^$/);
  await act(async () => {
    pending = [];
    deletion.resolve(
      new Response(
        JSON.stringify({
          id: "queued",
          message: "Processed text",
          delivery: "queue",
          target_response_id: 2,
        })
      )
    );
  });
  await waitFor(() => expect(textbox).toHaveTextContent("Processed text"));
  expect(screen.queryByTestId("queued-message-bar")).not.toBeInTheDocument();
});

test("an accepted message cannot be edited into a duplicate instruction", async () => {
  const user = setupUser();
  render(<AppInputBar {...props("streaming")} initialMessage="" />);
  await screen.findByText("Queued follow-up");
  pending = [];
  const textbox = screen.getByRole("textbox", { name: "Message input" });
  await user.click(textbox);
  await user.keyboard("{ArrowUp}{Enter}");
  expect(textbox).toHaveTextContent(/^$/);
  await waitFor(() =>
    expect(screen.queryByTestId("queued-message-bar")).not.toBeInTheDocument()
  );
});

test("reopening the composer loads the server queue without resubmitting it", async () => {
  const inputProps = props("streaming");
  const view = render(<AppInputBar {...inputProps} />);
  expect(await screen.findByText("Queued follow-up")).toBeVisible();
  view.unmount();
  render(<AppInputBar {...inputProps} />);
  expect(await screen.findByText("Queued follow-up")).toBeVisible();
  expect(requestLog.every((request) => request.method === "GET")).toBe(true);
  expect(inputProps.onSubmit).not.toHaveBeenCalled();
});

test("incognito keeps text in the composer while an answer is running", async () => {
  mockIncognito = true;
  const user = setupUser();
  render(<AppInputBar {...props("streaming")} />);
  const textbox = screen.getByRole("textbox", { name: "Message input" });
  await user.click(textbox);
  await user.keyboard("{Enter}{Control>}{Enter}{/Control}");
  expect(textbox).toHaveTextContent("Keep this draft");
  expect(fetchSpy).not.toHaveBeenCalled();
});

test("a successful queue request keeps text typed while it was pending", async () => {
  const user = setupUser();
  const submission = deferred<Response>();
  fetchSpy.mockImplementation(async (_url, init) =>
    init?.method === "POST"
      ? submission.promise
      : new Response(JSON.stringify(pending))
  );
  render(<AppInputBar {...props("streaming")} />);
  const textbox = screen.getByRole("textbox", { name: "Message input" });
  await user.click(textbox);
  await user.keyboard("{Enter} more");
  await act(async () => {
    const item = {
      id: "new",
      message: "Keep this draft",
      delivery: "queue" as const,
      target_response_id: 2,
    };
    pending.push(item);
    submission.resolve(new Response(JSON.stringify(item)));
  });
  expect(textbox).toHaveTextContent("Keep this draft more");
  expect(mockClearDraft).not.toHaveBeenCalled();
});

test("an input accepted before POST returns refreshes the active conversation", async () => {
  const user = setupUser();
  pending = [];
  render(<AppInputBar {...props("streaming")} />);
  await waitFor(() => expect(fetchSpy).toHaveBeenCalled());
  fetchSpy.mockImplementation(
    async (_url, init) =>
      new Response(
        JSON.stringify(
          init?.method === "POST"
            ? {
                id: "accepted",
                message: "Keep this draft",
                delivery: "send",
                target_response_id: 2,
              }
            : []
        )
      )
  );
  const textbox = screen.getByRole("textbox", { name: "Message input" });
  await user.click(textbox);
  await user.keyboard("{Control>}{Enter}{/Control}");
  await waitFor(() =>
    expect(mockRefreshChatSession).toHaveBeenCalledWith(
      "session",
      expect.any(String)
    )
  );
  await waitFor(() =>
    expect(screen.queryByTestId("queued-message-bar")).not.toBeInTheDocument()
  );
});

test("a failed queue-acceptance refresh offers recovery after the queue is empty", async () => {
  const saved = await fetchSettledChatSession("session");
  saved.messages = [
    "Question",
    "Answer",
    "Queued follow-up",
    "Queued answer",
  ].map(
    (message, index): BackendMessage => ({
      message_id: index + 1,
      message_type: index % 2 === 0 ? "user" : "assistant",
      message,
      parent_message: index === 0 ? null : index,
      latest_child_message: index === 3 ? null : index + 2,
      response_status: index % 2 === 0 ? null : "complete",
      research_type: null,
      rephrased_query: null,
      context_docs: null,
      time_sent: "2026-11-09T00:00:00Z",
      overridden_model: "",
      alternate_assistant_id: null,
      chat_session_id: "session",
      citations: null,
      files: [],
      tool_call: null,
      current_feedback: null,
      sub_questions: [],
      comments: null,
      parentMessageId: null,
      refined_answer_improvement: null,
      is_agentic: null,
      preferred_response_id: null,
      model_display_name: null,
      error: null,
    })
  );
  saved.packets = [[], []];
  const readiness = jest.requireActual<
    typeof import("@/lib/chat/sessionReadiness")
  >("@/lib/chat/sessionReadiness");
  jest
    .mocked(waitForChatResponseEnd)
    .mockImplementation(readiness.waitForChatResponseEnd);
  jest
    .mocked(fetchSettledChatSession)
    .mockImplementation(readiness.fetchSettledChatSession);
  jest
    .mocked(processRawChatHistory)
    .mockImplementation(
      jest.requireActual<typeof import("@/app/app/services/lib")>(
        "@/app/app/services/lib"
      ).processRawChatHistory
    );
  mockRefreshChatSession.mockImplementation(
    jest.requireActual<typeof import("@/lib/chat/settleChatSession")>(
      "@/lib/chat/settleChatSession"
    ).refreshChatSession
  );
  let refreshRequests = 0;
  fetchSpy.mockImplementation(async (input) => {
    const url = String(input);
    if (url.endsWith("/pending-messages"))
      return new Response(JSON.stringify(pending));
    if (url.endsWith("/status"))
      return new Response(
        JSON.stringify({ is_processing: false, current_stream: null })
      );
    if (url.includes("get-chat-session")) {
      refreshRequests++;
      return refreshRequests === 1
        ? new Response("Unavailable", { status: 503 })
        : new Response(JSON.stringify(saved));
    }
    throw new Error(`Unexpected request: ${url}`);
  });
  const log = jest.spyOn(console, "error").mockImplementation(() => {});
  try {
    const user = setupUser();
    const inputProps = props("input");
    const view = render(<AppInputBar {...inputProps} />);
    expect(await screen.findByText("Queued follow-up")).toBeVisible();
    pending = [];
    await waitFor(
      () => {
        expect(
          useChatSessionStore.getState().sessions.get("session")?.chatState
        ).toBe("unconfirmed");
      },
      { timeout: 2500 }
    );
    view.rerender(<AppInputBar {...inputProps} chatState="unconfirmed" />);
    expect(screen.queryByText("Queued follow-up")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Check again$/ }));
    await waitFor(() => {
      const session = useChatSessionStore.getState().sessions.get("session");
      expect(session?.chatState).toBe("input");
      expect(session?.messageTree.get(3)?.message).toBe("Queued follow-up");
      expect(session?.messageTree.get(4)?.message).toBe("Queued answer");
      expect(session?.uncaughtError).toBeNull();
    });
    expect(
      screen.getByRole("textbox", { name: "Message input" })
    ).toHaveTextContent("Keep this draft");
    expect(inputProps.onSubmit).not.toHaveBeenCalled();
    expect(refreshRequests).toBe(2);
  } finally {
    log.mockRestore();
  }
});
