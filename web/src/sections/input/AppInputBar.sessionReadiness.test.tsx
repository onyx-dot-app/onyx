import { mutate } from "swr";
import { ChatSessionSharedStatus, type Message } from "@/app/app/types";
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
} from "@/lib/chat/sessionReadiness";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import { useChatSessionQueue } from "@/lib/chat/hooks";
import type { PendingChatMessage } from "@/lib/chat/types";
import { SWR_KEYS } from "@/lib/swr-keys";

Element.prototype.scrollIntoView = jest.fn();

let mockSearchMode = false;
let mockIncognito = false;
let mockInterruptOnSend = false;
let pending: PendingChatMessage[] = [];
let fetchSpy: jest.SpiedFunction<typeof fetch>;

const mockClearDraft = jest.fn();
const mockWriteDraft = jest.fn();

jest.mock("@/lib/chat/sessionReadiness", () => ({
  waitForChatResponseEnd: jest.fn(),
  fetchSettledChatSession: jest.fn(),
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
jest.mock("@/components/voice/Waveform", () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock("@/sections/cards/FileCard", () => ({ FileCard: () => null }));

type ComposerProps = Omit<AppInputBarProps, "queue">;

/** The composer as chat pages mount it, with the session-level queue. */
function ChatInput(inputProps: ComposerProps) {
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
    toolConfiguration: {} as AppInputBarProps["toolConfiguration"],
  };
}

beforeEach(() => {
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
    },
  ];
  jest.mocked(waitForChatResponseEnd).mockReset();
  fetchSpy = jest
    .spyOn(global, "fetch")
    .mockImplementation(async (url, init) => {
      const method = init?.method ?? "GET";
      if (String(url).endsWith("/status"))
        return new Response(
          JSON.stringify({
            is_processing: false,
            current_stream: null,
            has_startable_input: false,
            latest_response_id: 2,
          })
        );
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
      return new Response(JSON.stringify(pending));
    });
  mockClearDraft.mockClear();
  mockWriteDraft.mockClear();
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
  fetchSpy.mockImplementation(async (_url, init) =>
    init?.method === "POST"
      ? new Response(JSON.stringify({ detail: "Response has finished" }), {
          status: 409,
        })
      : new Response(JSON.stringify(pending))
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
  fetchSpy.mockImplementation(async (_url, init) =>
    init?.method === "POST"
      ? submission.promise
      : new Response(JSON.stringify(pending))
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
  fetchSpy.mockImplementation(async (_url, init) =>
    init?.method === "POST"
      ? submission.promise
      : new Response(JSON.stringify(pending))
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
                has_startable_input: startable,
                latest_response_id: 2,
              })
            )
          : new Response(JSON.stringify(pending))
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
  fetchSpy.mockImplementation(async (_url, init) => {
    if (init?.method !== "POST") return new Response(JSON.stringify(pending));
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
            has_startable_input: false,
            latest_response_id: latestResponseId,
          })
        )
      : new Response(JSON.stringify(pending))
  );
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
  ["a live single-model stop", { turn_index: 0, model_index: 0 }],
  ["a replayed stop", { turn_index: 0 }],
])("Stop is withdrawn once %s arrives", async (_case, placement) => {
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
    packets: [{ placement, obj: { type: "stop" } }],
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

test.each([
  [
    "one model",
    false,
    {
      model_provider: "Provider",
      model_version: "picked-model",
      model_configuration_id: 7,
    },
  ],
  ["a multi-model comparison", true, null],
])(
  "a queued message runs with the model the picker shows for %s",
  async (_case, isMultiModelActive, expected) => {
    const user = setupUser();
    render(
      <ChatInput
        {...props("streaming")}
        isMultiModelActive={isMultiModelActive}
      />
    );
    await user.click(screen.getByRole("textbox", { name: "Message input" }));
    await user.keyboard("{Control>}{Enter}{/Control}");
    await waitFor(() => expect(pending).toHaveLength(2));
    expect(pending.at(-1)?.llm_override).toEqual(expected);
  }
);

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
  });
  await act(async () => {
    await mutate(() => true, undefined, { revalidate: false });
  });
  const user = setupUser();
  render(<ChatInput {...props("streaming")} initialMessage="" />, {
    swrConfig: { provider: undefined },
  });
  await screen.findByText("Second follow-up");
  await user.click(screen.getByRole("textbox", { name: "Message input" }));
  await user.keyboard("{ArrowUp}{ArrowUp}");
  expect(screen.getByRole("listitem", { current: true })).toHaveTextContent(
    "Queued follow-up"
  );

  // A turn takes the highlighted head.
  pending = pending.slice(1);
  await act(async () => {
    await mutate(SWR_KEYS.pendingChatMessages("session"));
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

test("an edit that finishes after a chat switch returns its text to its own chat", async () => {
  const user = setupUser();
  const withdrawal = deferred<Response>();
  fetchSpy.mockImplementation(async (_url, init) =>
    init?.method === "DELETE"
      ? withdrawal.promise
      : new Response(JSON.stringify(pending))
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
      "Queued follow-up"
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
    fetchSpy.mockImplementation(async (_url, init) =>
      init?.method === "POST"
        ? submission.promise
        : new Response(JSON.stringify(pending))
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
        "Keep this draft"
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
  fetchSpy.mockImplementation(async (_url, init) =>
    init?.method === "POST"
      ? submission.promise
      : new Response(JSON.stringify(pending))
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
      "Keep this draft"
    )
  );
});
