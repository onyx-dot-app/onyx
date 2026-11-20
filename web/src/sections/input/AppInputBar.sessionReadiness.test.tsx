import { mutate, type ScopedMutator, useSWRConfig } from "swr";
import {
  ChatFileType,
  ChatSessionSharedStatus,
  type Message,
} from "@/app/app/types";
import { type ProjectFile, UserFileStatus } from "@/lib/projects/types";
import {
  act,
  fireEvent,
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
  readChatSessionStatus,
} from "@/lib/chat/sessionReadiness";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import { useChatSessionQueue } from "@/lib/chat/hooks";
import { flushToolOptions } from "@/lib/tools/hooks";
import type { ChatSessionStatus, PendingChatMessage } from "@/lib/chat/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import { toast } from "@opal/layouts";
import { PacketType, StopReason } from "@/app/app/services/streamingModels";
import { useToolRequestUi } from "@/lib/chat/toolApprovals";
import { APPROVAL_PENDING_ERROR_CODE } from "@/app/app/types";

Element.prototype.scrollIntoView = jest.fn();

let mockSearchMode = false;
let mockIncognito = false;
let mockInterruptOnSend = false;
let pending: PendingChatMessage[] = [];
let mockMessageFiles: ProjectFile[] = [];
let fetchSpy: jest.SpiedFunction<typeof fetch>;

const mockClearDraft = jest.fn();
const mockWriteDraft = jest.fn();

jest.mock("@/lib/chat/sessionReadiness", () => ({
  waitForChatResponseEnd: jest.fn(),
  fetchSettledChatSession: jest.fn(),
  readChatSessionStatus: jest.fn(),
}));

jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({
    user: { preferences: { interrupt_on_send: mockInterruptOnSend } },
    isAdmin: false,
  }),
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
let mockChatId: string | null = "session";
jest.mock("@/lib/navigation/hooks", () => ({
  useAppPosition: () => ({ isNewSession: () => false, chat: () => mockChatId }),
}));
jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({ appName: "Onyx" }),
}));
jest.mock("@/lib/projects/providers", () => ({
  useProjectsContext: () => ({
    currentMessageFiles: mockMessageFiles,
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
const mockNoChatSkills = {
  entries: { skills: [], apps: [], mcpServers: [] },
  onInputFocus: () => undefined,
};
jest.mock("@/lib/skills/hooks", () => ({
  ...jest.requireActual("@/lib/skills/hooks"),
  useChatSkills: () => mockNoChatSkills,
}));
jest.mock("@/hooks/usePromptShortcuts", () => ({
  __esModule: true,
  default: () => ({ activePromptShortcuts: [] }),
}));
jest.mock("@/hooks/useDraft", () => ({
  draftKey: (scope: string, id: string) => `${scope}:${id}`,
  writeDraft: (...args: unknown[]) => mockWriteDraft(...args),
  readDraft: () => null,
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
jest.mock("@/sections/plugins/IntegrationConnectPrompt", () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock("@/lib/tools/hooks", () => ({
  ...jest.requireActual("@/lib/tools/hooks"),
  flushToolOptions: jest.fn(() => Promise.resolve()),
}));
jest.mock("@/components/voice/Waveform", () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock("@/sections/cards/FileCard", () => ({ FileCard: () => null }));

const IDLE_STATUS: ChatSessionStatus = {
  is_processing: false,
  current_stream: null,
  has_active_subagents: false,
  has_startable_input: false,
  approvals_version: "1",
  latest_response_id: 2,
};
let chatStatus = IDLE_STATUS;

/** The chat's status, or its pending messages for any other read. */
function readResponse(url: RequestInfo | URL): Response {
  return new Response(
    JSON.stringify(String(url).endsWith("/status") ? chatStatus : pending)
  );
}

type ComposerProps = Omit<AppInputBarProps, "queue">;

// Each render has its own SWR cache; tests revalidate keys through it.
let swrMutate: ScopedMutator;

/** The composer as chat pages mount it, with the session-level queue. */
function ChatInput(inputProps: ComposerProps) {
  swrMutate = useSWRConfig().mutate;
  const queue = useChatSessionQueue(!mockIncognito);
  return <AppInputBar {...inputProps} queue={queue} />;
}

function props(chatState: AppInputBarProps["chatState"]): ComposerProps {
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
    llmManager: {
      isLoadingProviders: false,
      currentLlm: {
        name: "Provider",
        provider: "openai",
        modelName: "picked-model",
        modelConfigurationId: 7,
      },
      hasTemperatureOverride: false,
      temperature: 0.5,
    } as AppInputBarProps["llmManager"],
    toolConfiguration: {
      optionsLoaded: true,
    } as AppInputBarProps["toolConfiguration"],
  };
}

beforeEach(() => {
  chatStatus = IDLE_STATUS;
  mockMessageFiles = [];
  mockChatId = "session";
  mockSearchMode = false;
  mockIncognito = false;
  mockInterruptOnSend = false;
  pending = [
    {
      id: "queued",
      message: "Queued follow-up",
      delivery: "queue",
      target_response_id: 2,
      deep_research: false,
      llm_override: null,
      mentions: [],
    },
  ];
  jest.mocked(waitForChatResponseEnd).mockReset();
  fetchSpy = jest
    .spyOn(global, "fetch")
    .mockImplementation(async (url, init) => {
      const method = init?.method ?? "GET";
      if (method === "POST" && String(url).endsWith("/interrupt")) {
        const id = String(url).split("/").at(-2);
        const item = pending.find((message) => message.id === id);
        pending = pending.filter((message) => message.id !== id);
        return new Response(
          JSON.stringify(item ?? { detail: "Already accepted" }),
          { status: item ? 200 : 409 }
        );
      }
      if (method === "POST") {
        const body: Omit<PendingChatMessage, "id"> = JSON.parse(
          String(init?.body)
        );
        const item = { id: `pending-${pending.length}`, ...body };
        pending.push(item);
        return new Response(JSON.stringify(item));
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
      return readResponse(url);
    });
  mockClearDraft.mockClear();
  mockWriteDraft.mockClear();
  jest.mocked(fetchSettledChatSession).mockImplementation(async () => ({
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
    approvals_version: chatStatus.approvals_version,
  }));
  useChatSessionStore.setState({ sessions: new Map(), currentSessionId: null });
  const store = useChatSessionStore.getState();
  // The chat's load showed the requests of the status's version.
  store.createSession("session", { approvalsVersion: "1" });
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
  const firstIdle = deferred<null>();
  const secondIdle = deferred<null>();
  jest
    .mocked(waitForChatResponseEnd)
    .mockImplementation((sessionId) =>
      sessionId === "session" ? firstIdle.promise : secondIdle.promise
    );
  const store = useChatSessionStore.getState();
  store.updateChatState("session", "unconfirmed");
  store.createSession("other", { chatState: "unconfirmed" });
  const { rerender } = render(<ChatInput {...props("unconfirmed")} />);

  await user.click(screen.getByRole("button", { name: /Check again$/ }));
  act(() => store.setCurrentSession("other"));
  rerender(<ChatInput {...props("unconfirmed")} />);
  expect(screen.getByRole("button", { name: /Check again$/ })).toBeEnabled();
  await user.click(screen.getByRole("button", { name: /Check again$/ }));

  act(() => store.setCurrentSession("session"));
  rerender(<ChatInput {...props("unconfirmed")} />);
  expect(screen.getByRole("button", { name: /Check again$/ })).toBeDisabled();
  await act(async () => firstIdle.resolve(null));
  act(() => store.setCurrentSession("other"));
  rerender(<ChatInput {...props("unconfirmed")} />);
  expect(screen.getByRole("button", { name: /Check again$/ })).toBeDisabled();
  await act(async () => secondIdle.resolve(null));
  expect(screen.getByRole("button", { name: /Check again$/ })).toBeEnabled();
});

test("search cannot submit or clear a draft while readiness is unconfirmed", async () => {
  mockSearchMode = true;
  const user = setupUser();
  const inputProps = props("unconfirmed");
  const { container } = render(<ChatInput {...inputProps} />);
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
  const { rerender } = render(<ChatInput {...inputProps} />);
  const stopping = screen.getByRole("button", { name: /Stopping…$/ });
  expect(stopping).toBeDisabled();
  const textbox = screen.getByRole("textbox", { name: "Message input" });
  await user.click(textbox);
  await user.keyboard("{Enter}");
  await user.click(stopping);
  expect(textbox).toHaveTextContent("Keep this draft");
  expect(inputProps.onSubmit).not.toHaveBeenCalled();
  expect(pending).toHaveLength(1);

  rerender(<ChatInput {...inputProps} chatState="input" />);
  expect(inputProps.onSubmit).not.toHaveBeenCalled();
  expect(textbox).toHaveTextContent("Keep this draft");
});

test("a send before the tool options load waits for them and then sends", async () => {
  const user = setupUser();
  const inputProps = props("input");
  const notLoaded = {
    ...inputProps,
    toolConfiguration: {
      optionsLoaded: false,
    } as AppInputBarProps["toolConfiguration"],
  };
  const { rerender } = render(<ChatInput {...notLoaded} />);
  const textbox = screen.getByRole("textbox", { name: "Message input" });
  await user.click(textbox);
  await user.keyboard("{Enter}");
  expect(inputProps.onSubmit).not.toHaveBeenCalled();
  expect(textbox).toHaveTextContent("Keep this draft");

  rerender(<ChatInput {...inputProps} />);
  await waitFor(() => expect(inputProps.onSubmit).toHaveBeenCalledTimes(1));
  expect(inputProps.onSubmit).toHaveBeenCalledWith(
    expect.objectContaining({ message: "Keep this draft" })
  );
});

test("a held send is dropped when the chat changes before the tool options load", async () => {
  const user = setupUser();
  const inputProps = props("input");
  const notLoaded = {
    ...inputProps,
    toolConfiguration: {
      optionsLoaded: false,
    } as AppInputBarProps["toolConfiguration"],
  };
  const { rerender } = render(<ChatInput {...notLoaded} />);
  await user.click(screen.getByRole("textbox", { name: "Message input" }));
  await user.keyboard("{Enter}");
  expect(inputProps.onSubmit).not.toHaveBeenCalled();

  mockChatId = "other";
  const otherChat = props("input");
  rerender(<ChatInput {...otherChat} />);
  await act(async () => {
    await Promise.resolve();
  });
  expect(otherChat.onSubmit).not.toHaveBeenCalled();
  expect(inputProps.onSubmit).not.toHaveBeenCalled();
});

test("a held send waits for pending files after the tool options load", async () => {
  const user = setupUser();
  const inputProps = props("input");
  const notLoaded = {
    ...inputProps,
    toolConfiguration: {
      optionsLoaded: false,
    } as AppInputBarProps["toolConfiguration"],
  };
  const { rerender } = render(<ChatInput {...notLoaded} />);
  await user.click(screen.getByRole("textbox", { name: "Message input" }));
  await user.keyboard("{Enter}");
  const file: ProjectFile = {
    id: "file-1",
    name: "notes.txt",
    project_id: null,
    user_id: null,
    file_id: "file-1",
    created_at: "2026-11-17T00:00:00Z",
    status: UserFileStatus.PROCESSING,
    file_type: "text/plain",
    last_accessed_at: "2026-11-17T00:00:00Z",
    chat_file_type: ChatFileType.PLAIN_TEXT,
    token_count: 1,
    chunk_count: 1,
  };
  mockMessageFiles = [file];
  rerender(<ChatInput {...inputProps} />);
  await act(async () => {
    await Promise.resolve();
  });
  expect(inputProps.onSubmit).not.toHaveBeenCalled();

  mockMessageFiles = [{ ...file, status: UserFileStatus.COMPLETED }];
  rerender(<ChatInput {...inputProps} disabled />);
  await act(async () => {
    await Promise.resolve();
  });
  expect(inputProps.onSubmit).not.toHaveBeenCalled();

  rerender(<ChatInput {...inputProps} />);
  await waitFor(() => expect(inputProps.onSubmit).toHaveBeenCalledTimes(1));
});

test("unconfirmed completion offers a retry and never submits the draft or queue", async () => {
  const user = setupUser();
  const inputProps = props("unconfirmed");
  render(<ChatInput {...inputProps} />);
  expect(screen.getByRole("button", { name: /Check again$/ })).toBeEnabled();
  const textbox = screen.getByRole("textbox", { name: "Message input" });
  await user.click(textbox);
  await user.keyboard("{Enter}");
  expect(inputProps.onSubmit).not.toHaveBeenCalled();
  expect(textbox).toHaveTextContent("Keep this draft");
  expect(pending).toHaveLength(1);
});

test.each([false, true])(
  "retrying completion preserves the draft and paused queue (failed acknowledgement: %s)",
  async (failedAcknowledgement) => {
    const user = setupUser();
    const idle = deferred<null>();
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
    const { rerender } = render(<ChatInput {...inputProps} />);
    await user.click(screen.getByRole("button", { name: /Check again$/ }));
    expect(screen.getByRole("button", { name: /Check again$/ })).toBeDisabled();
    expect(inputProps.onSubmit).not.toHaveBeenCalled();
    await act(async () => idle.resolve(null));
    expect(
      useChatSessionStore.getState().sessions.get("session")?.chatState
    ).toBe("input");
    rerender(<ChatInput {...inputProps} chatState="input" />);
    expect(
      screen.getByRole("textbox", { name: "Message input" })
    ).toHaveTextContent("Keep this draft");
    expect(pending).toHaveLength(1);
    expect(inputProps.onSubmit).not.toHaveBeenCalled();
    expect(fetchSettledChatSession).toHaveBeenCalled();
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
  const { rerender, container } = render(<ChatInput {...inputProps} />);
  await user.click(screen.getByRole("button", { name: /Check again$/ }));
  act(() => store.updateChatState("session", "streaming"));
  rerender(<ChatInput {...inputProps} chatState="streaming" />);
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
    render(<ChatInput {...inputProps} />);
    const textbox = screen.getByRole("textbox", { name: "Message input" });
    const hint = screen.getByTestId("pending-message-hint");
    expect(hint).toHaveAccessibleName(
      "Enter to send · Ctrl or Command + Enter to queue"
    );
    expect(textbox.closest("#onyx-chat-input")).toContainElement(hint);
    expect(screen.getByRole("button", { name: /^Send$/ })).toHaveTextContent(
      /^$/
    );
    expect(
      screen.queryByRole("button", { name: /^Send now$/ })
    ).not.toBeInTheDocument();
    await user.click(textbox);
    await user.keyboard(keys);
    await waitFor(() => expect(pending).toHaveLength(2));
    expect(pending[1]).toMatchObject({
      message: "Keep this draft",
      target_response_id: 2,
      delivery: keys === "{Enter}" ? "send" : "queue",
    });
    expect(inputProps.onSubmit).not.toHaveBeenCalled();
    await waitFor(() => expect(textbox).toHaveTextContent(/^$/));
    expect(hint).not.toBeInTheDocument();
    expect(await screen.findByText("Keep this draft")).toBeVisible();
  }
);

test("a failed submission returns its text to the composer", async () => {
  const user = setupUser();
  fetchSpy.mockImplementation(async (url, init) =>
    init?.method === "POST"
      ? new Response(JSON.stringify({ detail: "Response has finished" }), {
          status: 409,
        })
      : readResponse(url)
  );
  render(<ChatInput {...props("streaming")} />);
  const textbox = screen.getByRole("textbox", { name: "Message input" });
  await user.click(textbox);
  await user.keyboard("{Enter}");
  await waitFor(() => expect(textbox).toHaveTextContent("Keep this draft"));
  expect(screen.getAllByTestId("queued-message-bar")).toHaveLength(1);
  expect(pending).toHaveLength(1);
});

test("a failed submission keeps text typed while it was pending", async () => {
  const user = setupUser();
  const submission = deferred<Response>();
  fetchSpy.mockImplementation(async (url, init) =>
    init?.method === "POST" ? submission.promise : readResponse(url)
  );
  render(<ChatInput {...props("streaming")} />);
  const textbox = screen.getByRole("textbox", { name: "Message input" });
  await user.click(textbox);
  await user.keyboard("{Control>}{Enter}{/Control}more");
  await act(async () =>
    submission.resolve(
      new Response(JSON.stringify({ detail: "Queue is full" }), {
        status: 409,
      })
    )
  );
  await waitFor(() =>
    expect(textbox).toHaveTextContent(/^Keep this draft\s*more$/)
  );
});

/** Puts a request that waits for the user in the latest response. */
function awaitToolApproval() {
  const store = useChatSessionStore.getState();
  const tree = new Map(store.sessions.get("session")!.messageTree);
  tree.set(2, {
    ...tree.get(2)!,
    packets: [
      {
        placement: { turn_index: 1, tab_index: 0 },
        obj: {
          type: PacketType.TOOL_APPROVAL_REQUEST,
          approval_id: "approval-1",
          tool_call_id: "call-1",
          tool_name: "mcp__3__github__create_issue",
          display_name: "Create issue",
          arguments: {},
          agent_name: null,
        },
      },
    ],
  });
  store.updateSessionMessageTree("session", tree);
}

/** The server refuses new input while a reply waits for an approval. */
function refuseForApproval(url: RequestInfo | URL, init?: RequestInit) {
  return init?.method === "POST"
    ? new Response(
        JSON.stringify({
          error_code: APPROVAL_PENDING_ERROR_CODE,
          detail: "Approve or reject the pending tool calls",
        }),
        { status: 409 }
      )
    : readResponse(url);
}

test("a waiting card leaves the send to the server", async () => {
  awaitToolApproval();
  const user = setupUser();
  const inputProps = props("input");
  render(<ChatInput {...inputProps} />);

  await user.click(screen.getByRole("textbox", { name: "Message input" }));
  await user.keyboard("{Enter}");

  expect(inputProps.onSubmit).toHaveBeenCalledWith({
    message: "Keep this draft",
    mentions: [],
  });
});

test("a server refusal for a waiting approval keeps the draft and points at its card", async () => {
  useToolRequestUi.setState({
    localStatuses: new Map(),
    localAnswers: new Map(),
    nudge: null,
  });
  const warning = jest.spyOn(toast, "warning");
  awaitToolApproval();
  fetchSpy.mockImplementation(async (url, init) =>
    refuseForApproval(url, init)
  );
  const user = setupUser();
  render(<ChatInput {...props("streaming")} />);
  const textbox = screen.getByRole("textbox", { name: "Message input" });

  await user.click(textbox);
  await user.keyboard("{Enter}");

  await waitFor(() =>
    expect(useToolRequestUi.getState().nudge?.requestId).toBe("approval-1")
  );
  expect(textbox).toHaveTextContent("Keep this draft");
  expect(warning).toHaveBeenCalledWith(
    "Approve or reject the pending tool calls first."
  );
  expect(fetchSettledChatSession).not.toHaveBeenCalled();
});

test("a server refusal for an approval this tab does not show loads the server's cards", async () => {
  useToolRequestUi.setState({
    localStatuses: new Map(),
    localAnswers: new Map(),
    nudge: null,
  });
  const warning = jest.spyOn(toast, "warning");
  const error = jest.spyOn(toast, "error");
  const user = setupUser();
  fetchSpy.mockImplementation(async (url, init) =>
    refuseForApproval(url, init)
  );
  render(<ChatInput {...props("streaming")} />);
  const textbox = screen.getByRole("textbox", { name: "Message input" });

  await user.click(textbox);
  await user.keyboard("{Enter}");

  await waitFor(() => expect(textbox).toHaveTextContent("Keep this draft"));
  expect(warning).toHaveBeenCalledWith(
    "Answer the pending approval requests or questions first."
  );
  expect(error).not.toHaveBeenCalled();
  // This tab has no card for the other tab's turn, so it loads the session.
  expect(useToolRequestUi.getState().nudge).toBeNull();
  await waitFor(() => expect(fetchSettledChatSession).toHaveBeenCalled());
});

/** Puts a question that waits for the user's answer in the latest response. */
function awaitQuestion() {
  const store = useChatSessionStore.getState();
  const tree = new Map(store.sessions.get("session")!.messageTree);
  tree.set(2, {
    ...tree.get(2)!,
    packets: [
      {
        placement: { turn_index: 1, tab_index: 0 },
        obj: {
          type: PacketType.TOOL_QUESTION_REQUEST,
          question_request_id: "question-1",
          tool_call_id: "call-1",
          questions: [
            {
              id: "scope",
              header: "Scope",
              question: "Which files?",
              options: [
                { label: "All", description: "Every file." },
                { label: "Docs", description: "Only the docs." },
              ],
            },
          ],
        },
      },
    ],
  });
  store.updateSessionMessageTree("session", tree);
}

const ANSWERS_URL = "/api/chat/question-requests/question-1/answers";

/** Answers the answers route with `response`; other reads as usual. */
function answerWith(response: () => Response) {
  const answered = jest.fn();
  fetchSpy.mockImplementation(async (url, init) => {
    if (String(url) === ANSWERS_URL) {
      answered(JSON.parse(String(init?.body)));
      return response();
    }
    return readResponse(url);
  });
  return answered;
}

describe("while a question waits", () => {
  beforeEach(() => {
    useToolRequestUi.setState({
      localStatuses: new Map(),
      localAnswers: new Map(),
      nudge: null,
    });
    awaitQuestion();
    jest.mocked(readChatSessionStatus).mockResolvedValue(IDLE_STATUS);
  });

  test.each(["input", "streaming"] as const)(
    "typed text answers it instead of starting a turn (%s)",
    async (chatState) => {
      useChatSessionStore.getState().updateChatState("session", chatState);
      const answered = answerWith(
        () =>
          new Response(
            JSON.stringify({
              question_request_id: "question-1",
              continuation: null,
            })
          )
      );
      const user = setupUser();
      const inputProps = props(chatState);
      render(<ChatInput {...inputProps} />);
      const textbox = screen.getByRole("textbox", { name: "Message input" });

      await user.click(textbox);
      await user.keyboard("{Enter}");

      await waitFor(() =>
        expect(answered).toHaveBeenCalledWith({ message: "Keep this draft" })
      );
      expect(inputProps.onSubmit).not.toHaveBeenCalled();
      expect(pending).toHaveLength(1);
      expect(textbox).toHaveTextContent("");
      // The card shows the answer until the resolution arrives, so later
      // text starts a turn again.
      await waitFor(() =>
        expect(
          useToolRequestUi.getState().localAnswers.get("question-1")
        ).toEqual({
          kind: "answered",
          answers: null,
          message: "Keep this draft",
        })
      );
    }
  );

  test("a question answered here no longer takes typed text", async () => {
    useToolRequestUi.getState().recordAnswer("question-1", {
      kind: "answered",
      answers: [{ question_id: "scope", option_label: "Docs" }],
      message: null,
    });
    const answered = answerWith(() => new Response("{}"));
    const user = setupUser();
    const inputProps = props("input");
    render(<ChatInput {...inputProps} />);

    await user.click(screen.getByRole("textbox", { name: "Message input" }));
    await user.keyboard("{Enter}");

    expect(inputProps.onSubmit).toHaveBeenCalledWith({
      message: "Keep this draft",
      mentions: [],
    });
    expect(answered).not.toHaveBeenCalled();
  });

  test("Stop stays available while the main button sends the answer", async () => {
    useChatSessionStore.getState().updateChatState("session", "streaming");
    const user = setupUser();
    const inputProps = props("streaming");
    render(<ChatInput {...inputProps} />);

    await user.click(screen.getByRole("button", { name: "Stop generating" }));

    expect(inputProps.stopGenerating).toHaveBeenCalled();
  });

  test("a message with files is held, with the reason", async () => {
    mockMessageFiles = [
      {
        id: "file-1",
        name: "notes.txt",
        project_id: null,
        user_id: null,
        file_id: "file-1",
        created_at: "2026-11-17T00:00:00Z",
        status: UserFileStatus.COMPLETED,
        file_type: "text/plain",
        last_accessed_at: "2026-11-17T00:00:00Z",
        chat_file_type: ChatFileType.PLAIN_TEXT,
        token_count: 1,
        chunk_count: 1,
      },
    ];
    const answered = answerWith(() => new Response("{}"));
    const user = setupUser();
    const inputProps = props("input");
    const { container } = render(<ChatInput {...inputProps} />);
    const textbox = screen.getByRole("textbox", { name: "Message input" });

    await user.click(textbox);
    await user.keyboard("{Enter}");

    expect(
      screen.getByText(
        "Answers to the agent's questions can't include files. Remove the files to answer."
      )
    ).toBeInTheDocument();
    expect(
      container.querySelector("#onyx-chat-input-send-button")
    ).toBeDisabled();
    expect(answered).not.toHaveBeenCalled();
    expect(inputProps.onSubmit).not.toHaveBeenCalled();
    expect(textbox).toHaveTextContent("Keep this draft");
  });

  test("an approval that still waits points at its card and keeps the text", async () => {
    const tree = new Map(
      useChatSessionStore.getState().sessions.get("session")!.messageTree
    );
    const answer = tree.get(2)!;
    tree.set(2, {
      ...answer,
      packets: [
        ...answer.packets,
        {
          placement: { turn_index: 1, tab_index: 1 },
          obj: {
            type: PacketType.TOOL_APPROVAL_REQUEST,
            approval_id: "approval-1",
            tool_call_id: "call-2",
            tool_name: "mcp__3__github__create_issue",
            display_name: "Create issue",
            arguments: {},
            agent_name: null,
          },
        },
      ],
    });
    useChatSessionStore.getState().updateSessionMessageTree("session", tree);
    answerWith(
      () =>
        new Response(
          JSON.stringify({
            error_code: APPROVAL_PENDING_ERROR_CODE,
            detail: "Approve or reject the pending requests",
          }),
          { status: 409 }
        )
    );
    const warning = jest.spyOn(toast, "warning");
    const user = setupUser();
    render(<ChatInput {...props("input")} />);
    const textbox = screen.getByRole("textbox", { name: "Message input" });

    await user.click(textbox);
    await user.keyboard("{Enter}");

    await waitFor(() =>
      expect(useToolRequestUi.getState().nudge?.requestId).toBe("approval-1")
    );
    expect(warning).toHaveBeenCalledWith(
      "Approve or reject the pending tool calls first."
    );
    await waitFor(() => expect(textbox).toHaveTextContent("Keep this draft"));
    expect(useToolRequestUi.getState().localAnswers.size).toBe(0);
  });

  test.each([409, 404])(
    "a question that no longer waits (%s) closes and keeps the text",
    async (status) => {
      answerWith(
        () =>
          new Response(
            JSON.stringify({ detail: "This question no longer waits" }),
            { status }
          )
      );
      const user = setupUser();
      render(<ChatInput {...props("input")} />);
      const textbox = screen.getByRole("textbox", { name: "Message input" });

      await user.click(textbox);
      await user.keyboard("{Enter}");

      await waitFor(() =>
        expect(
          useToolRequestUi.getState().localAnswers.get("question-1")
        ).toEqual({ kind: "closed" })
      );
      await waitFor(() => expect(textbox).toHaveTextContent("Keep this draft"));
      // Another answer can have continued the reply.
      expect(readChatSessionStatus).toHaveBeenCalledWith("session");
    }
  );

  test("another refusal shows the server's reason and keeps the text", async () => {
    answerWith(
      () =>
        new Response(
          JSON.stringify({
            error_code: "PAYLOAD_TOO_LARGE",
            detail: "A message can have at most 100 bytes",
          }),
          { status: 413 }
        )
    );
    const error = jest.spyOn(toast, "error");
    const user = setupUser();
    render(<ChatInput {...props("input")} />);
    const textbox = screen.getByRole("textbox", { name: "Message input" });

    await user.click(textbox);
    await user.keyboard("{Enter}");

    await waitFor(() =>
      expect(error).toHaveBeenCalledWith("A message can have at most 100 bytes")
    );
    await waitFor(() => expect(textbox).toHaveTextContent("Keep this draft"));
    expect(useToolRequestUi.getState().localAnswers.size).toBe(0);
  });
});

test("a queued message waits for the chat's tool selection to save", async () => {
  const user = setupUser();
  const saved = deferred<void>();
  const flush = jest.mocked(flushToolOptions);
  flush.mockReturnValueOnce(saved.promise);
  const posted = jest.fn();
  fetchSpy.mockImplementation(async (url, init) => {
    if (init?.method === "POST") {
      posted();
      return new Response(JSON.stringify(pending[0]));
    }
    return readResponse(url);
  });
  render(<ChatInput {...props("streaming")} />);
  await user.click(screen.getByRole("textbox", { name: "Message input" }));
  await user.keyboard("{Control>}{Enter}{/Control}");
  await waitFor(() => expect(flush).toHaveBeenCalledWith("session"));
  expect(posted).not.toHaveBeenCalled();
  await act(async () => saved.resolve());
  await waitFor(() => expect(posted).toHaveBeenCalledTimes(1));
});

test("an accepted message cannot be edited into a duplicate instruction", async () => {
  const user = setupUser();
  render(<ChatInput {...props("streaming")} initialMessage="" />);
  await screen.findByText("Queued follow-up");
  pending = [];
  const textbox = screen.getByRole("textbox", { name: "Message input" });
  await user.click(textbox);
  await user.click(
    screen.getByRole("button", {
      name: "Edit queued message: Queued follow-up",
    })
  );
  expect(textbox).toHaveTextContent(/^$/);
  await waitFor(() =>
    expect(screen.queryByTestId("queued-message-bar")).not.toBeInTheDocument()
  );
});

test("incognito keeps text in the composer while an answer is running", async () => {
  mockIncognito = true;
  const user = setupUser();
  render(<ChatInput {...props("streaming")} />);
  const textbox = screen.getByRole("textbox", { name: "Message input" });
  await user.click(textbox);
  await user.keyboard("{Enter}{Control>}{Enter}{/Control}");
  expect(textbox).toHaveTextContent("Keep this draft");
  expect(fetchSpy).not.toHaveBeenCalled();
  expect(screen.getByTestId("pending-message-hint")).toHaveTextContent(
    "Wait for the response to finish in incognito chat."
  );
});

test("a successful queue request keeps text typed while it was pending", async () => {
  const user = setupUser();
  const submission = deferred<Response>();
  fetchSpy.mockImplementation(async (url, init) =>
    init?.method === "POST" ? submission.promise : readResponse(url)
  );
  render(<ChatInput {...props("streaming")} />);
  const textbox = screen.getByRole("textbox", { name: "Message input" });
  await user.click(textbox);
  await user.keyboard("{Control>}{Enter}{/Control} more");
  await act(async () => {
    const item = {
      id: "new",
      message: "Keep this draft",
      delivery: "queue" as const,
      target_response_id: 2,
      deep_research: false,
      llm_override: null,
      mentions: [],
    };
    pending.push(item);
    submission.resolve(new Response(JSON.stringify(item)));
  });
  expect(textbox).toHaveTextContent("more");
  expect(mockClearDraft).toHaveBeenCalled();
});

test.each([true, false])(
  "an idle chat polls for a server-started turn only while input can start one (%s)",
  async (startable) => {
    jest.useFakeTimers();
    try {
      let processing = false;
      fetchSpy.mockImplementation(async (url) =>
        String(url).endsWith("/status")
          ? new Response(
              JSON.stringify({
                is_processing: processing,
                current_stream: null,
                has_active_subagents: false,
                has_startable_input: startable,
                approvals_version: "1",
                latest_response_id: 2,
              })
            )
          : readResponse(url)
      );
      // An accepted "Send now" leaves the list before its turn starts; a
      // paused queue keeps its messages.
      if (startable) pending = [];
      render(<ChatInput {...props("input")} />);
      await act(async () => jest.advanceTimersByTimeAsync(0));
      expect(fetchSettledChatSession).not.toHaveBeenCalled();

      processing = true;
      await act(async () => jest.advanceTimersByTimeAsync(4000));
      if (startable) expect(fetchSettledChatSession).toHaveBeenCalled();
      else expect(fetchSettledChatSession).not.toHaveBeenCalled();
    } finally {
      jest.useRealTimers();
    }
  }
);

test("input sent during a slow request stays in the composer until it ends", async () => {
  const user = setupUser();
  const accepted = deferred<void>();
  const posted: string[] = [];
  fetchSpy.mockImplementation(async (url, init) => {
    if (init?.method !== "POST") return readResponse(url);
    const body: Omit<PendingChatMessage, "id"> = JSON.parse(String(init.body));
    posted.push(body.message);
    if (posted.length === 1) await accepted.promise;
    const item = { id: `pending-${pending.length}`, ...body };
    pending.push(item);
    return new Response(JSON.stringify(item));
  });
  render(<ChatInput {...props("streaming")} />);
  const textbox = screen.getByRole("textbox", { name: "Message input" });
  await user.click(textbox);
  await user.keyboard("{Control>}{Enter}{/Control}");
  await waitFor(() => expect(textbox).toHaveTextContent(/^$/));
  await user.keyboard("Second{Control>}{Enter}{/Control}");
  expect(textbox).toHaveTextContent("Second");
  expect(posted).toEqual(["Keep this draft"]);

  await act(async () => accepted.resolve());
  await user.keyboard("{Control>}{Enter}{/Control}");
  await waitFor(() => expect(posted).toEqual(["Keep this draft", "Second"]));
  expect(await screen.findByText("Second")).toBeVisible();
});

test("a turn found by a readiness check during completion loads once the chat is idle", async () => {
  let latestResponseId = 2;
  fetchSpy.mockImplementation(async (url) =>
    String(url).endsWith("/status")
      ? new Response(
          JSON.stringify({
            is_processing: false,
            current_stream: null,
            has_active_subagents: false,
            has_startable_input: false,
            approvals_version: "1",
            latest_response_id: latestResponseId,
          })
        )
      : readResponse(url)
  );
  // Readiness checks share their reads through the default SWR cache, so only
  // this test renders on it.
  await act(async () => {
    await mutate(() => true, undefined, { revalidate: false });
  });
  const store = useChatSessionStore.getState();
  store.updateChatState("session", "streaming");
  render(<ChatInput {...props("streaming")} initialMessage="" />, {
    swrConfig: { provider: undefined },
  });
  await screen.findByText("Queued follow-up");

  // Queued turns ran while this browser confirmed its own response ended.
  latestResponseId = 4;
  const { waitForChatResponseEnd: readStatus } = jest.requireActual<
    typeof import("@/lib/chat/sessionReadiness")
  >("@/lib/chat/sessionReadiness");
  await act(async () => {
    await readStatus("session", 2);
  });
  expect(fetchSettledChatSession).not.toHaveBeenCalled();

  act(() => store.updateChatState("session", "input"));
  await waitFor(() => expect(fetchSettledChatSession).toHaveBeenCalled());
});

function interruptRequests() {
  return fetchSpy.mock.calls.filter(([url]) =>
    String(url).endsWith("/interrupt")
  );
}

test.each([
  ["a live single-model stop", { turn_index: 0, model_index: 0 }, undefined],
  ["a replayed stop", { turn_index: 0 }, undefined],
  ["an approval wait's stop", { turn_index: 0 }, StopReason.AWAITING_USER],
])("Stop is withdrawn once %s arrives", async (_case, placement, reason) => {
  const user = setupUser();
  const store = useChatSessionStore.getState();
  store.updateChatState("session", "streaming");
  const inputProps = { ...props("streaming"), initialMessage: "" };
  const { container } = render(<ChatInput {...inputProps} />);
  const send = container.querySelector<HTMLButtonElement>(
    "#onyx-chat-input-send-button"
  );
  if (!send) throw new Error("Send button is missing");
  expect(send).toBeEnabled();

  // The reader has the stop packet while the answer still renders.
  const tree = new Map(
    useChatSessionStore.getState().sessions.get("session")!.messageTree
  );
  const answer = tree.get(2)!;
  tree.set(2, {
    ...answer,
    packets: [{ placement, obj: { type: "stop", stop_reason: reason } }],
  });
  act(() => store.updateSessionMessageTree("session", tree));
  expect(send).toBeDisabled();
  await user.click(send);
  expect(inputProps.stopGenerating).not.toHaveBeenCalled();

  // Text typed now still reaches the server as pending input.
  await user.click(screen.getByRole("textbox", { name: "Message input" }));
  await user.keyboard("Next{Enter}");
  await waitFor(() => expect(pending).toHaveLength(2));
});

test("Stop stays while another model of the turn still runs", async () => {
  const store = useChatSessionStore.getState();
  store.updateChatState("session", "streaming");
  const { container } = render(
    <ChatInput {...props("streaming")} initialMessage="" />
  );
  const send = container.querySelector<HTMLButtonElement>(
    "#onyx-chat-input-send-button"
  );
  if (!send) throw new Error("Send button is missing");

  const tree = new Map(
    useChatSessionStore.getState().sessions.get("session")!.messageTree
  );
  const question = tree.get(1)!;
  const answer = tree.get(2)!;
  tree.set(1, { ...question, childrenNodeIds: [2, 3] });
  tree.set(2, {
    ...answer,
    packets: [
      { placement: { turn_index: 0, model_index: 0 }, obj: { type: "stop" } },
    ],
  });
  tree.set(3, { ...answer, nodeId: 3, messageId: 3, packets: [] });
  act(() => store.updateSessionMessageTree("session", tree));
  expect(send).toBeEnabled();

  tree.set(3, {
    ...answer,
    nodeId: 3,
    messageId: 3,
    packets: [
      { placement: { turn_index: 0, model_index: 1 }, obj: { type: "stop" } },
    ],
  });
  act(() => store.updateSessionMessageTree("session", new Map(tree)));
  expect(send).toBeDisabled();
});

test.each([
  ["an agent with search", "SearchTool", true],
  ["an agent without search", "ImageGenerationTool", false],
])(
  "a queued message keeps Deep Research for %s",
  async (_case, inCodeToolId, expected) => {
    const user = setupUser();
    const activeAgent = {
      id: 0,
      tools: [{ id: 1, in_code_tool_id: inCodeToolId }],
    } as AppInputBarProps["activeAgent"];
    render(
      <ChatInput
        {...props("streaming")}
        deepResearchEnabled
        activeAgent={activeAgent}
      />
    );
    await user.click(screen.getByRole("textbox", { name: "Message input" }));
    await user.keyboard("{Control>}{Enter}{/Control}");
    await waitFor(() => expect(pending).toHaveLength(2));
    expect(pending.at(-1)?.deep_research).toBe(expected);
  }
);

test("a queued message runs with the model the picker shows", async () => {
  const user = setupUser();
  render(<ChatInput {...props("streaming")} />);
  await user.click(screen.getByRole("textbox", { name: "Message input" }));
  await user.keyboard("{Control>}{Enter}{/Control}");
  await waitFor(() => expect(pending).toHaveLength(2));
  expect(pending.at(-1)?.llm_override).toEqual({
    model_provider: "Provider",
    model_version: "picked-model",
    model_configuration_id: 7,
  });
});

test("a multi-model comparison queues nothing and says why", async () => {
  const user = setupUser();
  render(<ChatInput {...props("streaming")} isMultiModelActive />);
  await screen.findByText("Queued follow-up");
  await user.click(screen.getByRole("textbox", { name: "Message input" }));
  await user.keyboard("{Control>}{Enter}{/Control}");
  await user.keyboard("{Enter}");
  expect(
    await screen.findByText(
      "Queueing is unavailable while comparing models. Choose one model to queue messages."
    )
  ).toBeInTheDocument();
  expect(pending).toHaveLength(1);
});

test("every pending write refreshes the chat status", async () => {
  const user = setupUser();
  render(<ChatInput {...props("streaming")} />);
  await screen.findByText("Queued follow-up");
  const statusReads = () =>
    fetchSpy.mock.calls.filter(([url]) => String(url).endsWith("/status"))
      .length;
  await waitFor(() => expect(statusReads()).toBe(1));
  await user.click(screen.getByRole("textbox", { name: "Message input" }));
  await user.keyboard("{Enter}");
  await waitFor(() => expect(statusReads()).toBe(2));
  await user.click(
    screen.getByRole("button", {
      name: "Remove queued message: Queued follow-up",
    })
  );
  await waitFor(() => expect(statusReads()).toBe(3));
});

test("Send now works after a keyboard highlight", async () => {
  const user = setupUser();
  render(<ChatInput {...props("streaming")} initialMessage="" />);
  await screen.findByText("Queued follow-up");
  await user.click(screen.getByRole("textbox", { name: "Message input" }));
  await user.keyboard("{ArrowUp}");
  expect(screen.getByRole("listitem", { current: true })).toHaveTextContent(
    "Queued follow-up"
  );
  await user.click(
    screen.getByRole("button", { name: "Send now: Queued follow-up" })
  );
  await waitFor(() => expect(interruptRequests()).toHaveLength(1));
  // The interrupted message leaves the queue.
  await waitFor(() =>
    expect(screen.queryByTestId("queued-message-bar")).not.toBeInTheDocument()
  );
});

test("Enter on a highlighted message that left the queue does not reach the next one", async () => {
  pending.push({
    id: "second",
    message: "Second follow-up",
    delivery: "queue",
    target_response_id: 2,
    deep_research: false,
    llm_override: null,
    mentions: [],
  });
  const user = setupUser();
  render(<ChatInput {...props("streaming")} initialMessage="" />);
  await screen.findByText("Second follow-up");
  await user.click(screen.getByRole("textbox", { name: "Message input" }));
  await user.keyboard("{ArrowUp}{ArrowUp}");
  expect(screen.getByRole("listitem", { current: true })).toHaveTextContent(
    "Queued follow-up"
  );

  // A turn takes the highlighted head.
  pending = pending.slice(1);
  await act(async () => {
    await swrMutate(SWR_KEYS.pendingChatMessages("session"));
  });
  await waitFor(() =>
    expect(screen.queryByText("Queued follow-up")).not.toBeInTheDocument()
  );
  expect(
    screen.queryByRole("listitem", { current: true })
  ).not.toBeInTheDocument();
  await user.keyboard("{Enter}");
  expect(interruptRequests()).toHaveLength(0);
});

test("an IME composition Enter does not send a highlighted message now", async () => {
  const user = setupUser();
  render(<ChatInput {...props("streaming")} initialMessage="" />);
  await screen.findByText("Queued follow-up");
  const textbox = screen.getByRole("textbox", { name: "Message input" });
  await user.click(textbox);
  await user.keyboard("{ArrowUp}");
  fireEvent.keyDown(textbox, { key: "Enter", isComposing: true });
  expect(screen.getByRole("listitem", { current: true })).toHaveTextContent(
    "Queued follow-up"
  );
  expect(interruptRequests()).toHaveLength(0);
});

test("an edited queued message is saved as the draft before the composer shows it", async () => {
  const user = setupUser();
  render(<ChatInput {...props("streaming")} initialMessage="" />);
  await user.click(
    await screen.findByRole("button", {
      name: "Edit queued message: Queued follow-up",
    })
  );
  const textbox = screen.getByRole("textbox", { name: "Message input" });
  await waitFor(() => expect(textbox).toHaveTextContent(/^Queued follow-up$/));
  // A chat switch cancels the composer's delayed save, so the text is saved now.
  expect(mockWriteDraft).toHaveBeenCalledWith(
    "chat:session",
    { message: "Queued follow-up", mentions: [] },
    expect.any(Function)
  );
});

test("an edited queued message keeps its picks, and a send carries them into the running response", async () => {
  pending = [
    {
      ...pending[0]!,
      message: "@code-review queued",
      mentions: [{ type: "skill", name: "code-review" }],
    },
  ];
  const user = setupUser();
  render(<ChatInput {...props("streaming")} initialMessage="" />);
  await user.click(
    await screen.findByRole("button", {
      name: "Edit queued message: @code-review queued",
    })
  );
  const textbox = screen.getByRole("textbox", { name: "Message input" });
  await waitFor(() =>
    expect(textbox).toHaveTextContent(/^@code-review queued$/)
  );
  expect(textbox.querySelectorAll('[data-mention-type="skill"]')).toHaveLength(
    1
  );

  await user.type(textbox, "{Enter}");
  await waitFor(() => expect(pending).toHaveLength(1));
  expect(pending[0]).toMatchObject({
    message: "@code-review queued",
    delivery: "send",
    mentions: [{ type: "skill", name: "code-review" }],
  });
});

test("an edit that finishes after a chat switch returns its text to its own chat", async () => {
  const user = setupUser();
  const withdrawal = deferred<Response>();
  fetchSpy.mockImplementation(async (url, init) =>
    init?.method === "DELETE" ? withdrawal.promise : readResponse(url)
  );
  const store = useChatSessionStore.getState();
  store.createSession("other");
  render(<ChatInput {...props("streaming")} initialMessage="" />);
  await user.click(
    await screen.findByRole("button", {
      name: "Edit queued message: Queued follow-up",
    })
  );
  const textbox = screen.getByRole("textbox", { name: "Message input" });
  expect(textbox).toHaveAttribute("contenteditable", "false");

  act(() => store.setCurrentSession("other"));
  expect(textbox).toHaveAttribute("contenteditable", "true");
  await act(async () =>
    withdrawal.resolve(new Response(JSON.stringify(pending[0])))
  );
  await waitFor(() =>
    expect(mockWriteDraft).toHaveBeenCalledWith(
      "chat:session",
      { message: "Queued follow-up", mentions: [] },
      expect.any(Function)
    )
  );
  expect(textbox).toHaveTextContent(/^$/);
});

test.each([
  ["a chat page", "session"],
  ["a page without the chat in its URL", null],
])(
  "a failed submission after a chat switch returns its text to its own chat's draft on %s",
  async (_page, chatId) => {
    mockChatId = chatId;
    const user = setupUser();
    const submission = deferred<Response>();
    fetchSpy.mockImplementation(async (url, init) =>
      init?.method === "POST" ? submission.promise : readResponse(url)
    );
    useChatSessionStore.getState().createSession("other");
    render(<ChatInput {...props("streaming")} />);
    await user.click(screen.getByRole("textbox", { name: "Message input" }));
    await user.keyboard("{Control>}{Enter}{/Control}");
    act(() => useChatSessionStore.getState().setCurrentSession("other"));
    await act(async () =>
      submission.resolve(new Response("{}", { status: 409 }))
    );
    await waitFor(() =>
      expect(mockWriteDraft).toHaveBeenCalledWith(
        "chat:session",
        { message: "Keep this draft", mentions: [] },
        expect.any(Function)
      )
    );
    expect(mockWriteDraft).not.toHaveBeenCalledWith(
      "chat:new",
      expect.anything()
    );
  }
);

test("a failed submission that ends after the composer closes goes to the chat's draft", async () => {
  const user = setupUser();
  const submission = deferred<Response>();
  fetchSpy.mockImplementation(async (url, init) =>
    init?.method === "POST" ? submission.promise : readResponse(url)
  );
  // The page keeps the chat's queue while the composer closes.
  function Page({ composerOpen }: { composerOpen: boolean }) {
    const queue = useChatSessionQueue(true);
    return composerOpen ? (
      <AppInputBar {...props("streaming")} queue={queue} />
    ) : null;
  }
  const view = render(<Page composerOpen />);
  await user.click(screen.getByRole("textbox", { name: "Message input" }));
  await user.keyboard("{Control>}{Enter}{/Control}");
  view.rerender(<Page composerOpen={false} />);
  await act(async () =>
    submission.resolve(new Response("{}", { status: 409 }))
  );
  await waitFor(() =>
    expect(mockWriteDraft).toHaveBeenCalledWith(
      "chat:session",
      { message: "Keep this draft", mentions: [] },
      expect.any(Function)
    )
  );
});

test("Stop subagents interrupts background work and refreshes the status", async () => {
  let active = true;
  fetchSpy.mockImplementation(async (url, init) => {
    const path = String(url);
    if (path.endsWith("/stop-subagents")) {
      active = false;
      return new Response(JSON.stringify(null));
    }
    if (path.endsWith("/status"))
      return new Response(
        JSON.stringify({
          is_processing: false,
          current_stream: null,
          has_active_subagents: active,
          has_startable_input: false,
          approvals_version: "1",
          latest_response_id: 2,
        })
      );
    return new Response(JSON.stringify(init?.method ? null : pending));
  });
  const user = setupUser();
  render(<ChatInput {...props("input")} initialMessage="" />);
  const stop = await screen.findByRole("button", { name: "Stop subagents" });
  // Screen readers announce the status text without the control inside it.
  expect(screen.getByRole("status")).not.toContainElement(stop);
  await user.click(stop);
  await waitFor(() =>
    expect(screen.queryByTestId("subagent-activity")).not.toBeInTheDocument()
  );
  expect(
    fetchSpy.mock.calls.filter(
      ([url, init]) =>
        String(url) === "/api/chat/chat-session/session/stop-subagents" &&
        init?.method === "POST"
    )
  ).toHaveLength(1);
});

describe("approvals version in the status", () => {
  test("an idle chat reloads only when the version differs from its load", async () => {
    const statusReads = () =>
      fetchSpy.mock.calls.filter(([url]) => String(url).endsWith("/status"))
        .length;
    render(<ChatInput {...props("input")} initialMessage="" />);
    await waitFor(() => expect(statusReads()).toBe(1));

    // The same version again: the chat already shows every request.
    await act(async () => {
      await swrMutate(SWR_KEYS.chatSessionStatus("session"));
    });
    expect(statusReads()).toBe(2);
    expect(fetchSettledChatSession).not.toHaveBeenCalled();

    // A background agent opened or resolved a request.
    chatStatus = { ...IDLE_STATUS, approvals_version: "2" };
    await act(async () => {
      await swrMutate(SWR_KEYS.chatSessionStatus("session"));
    });
    await waitFor(() =>
      expect(fetchSettledChatSession).toHaveBeenCalledTimes(1)
    );
    // The reload's version is the chat's new baseline.
    await waitFor(() =>
      expect(
        useChatSessionStore.getState().sessions.get("session")?.approvalsVersion
      ).toBe("2")
    );
    await act(async () => {
      await swrMutate(SWR_KEYS.chatSessionStatus("session"));
    });
    expect(fetchSettledChatSession).toHaveBeenCalledTimes(1);
  });

  test("a status read that finds a version the load did not show reloads", async () => {
    chatStatus = { ...IDLE_STATUS, approvals_version: "2" };
    render(<ChatInput {...props("input")} initialMessage="" />);
    await waitFor(() =>
      expect(fetchSettledChatSession).toHaveBeenCalledTimes(1)
    );
  });
});
