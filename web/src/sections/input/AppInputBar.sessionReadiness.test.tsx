import { mutate } from "swr";
import { ChatSessionSharedStatus, type Message } from "@/app/app/types";
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
import { useChatSessionQueue } from "@/lib/chat/hooks";
import type { PendingChatMessage } from "@/lib/chat/types";

Element.prototype.scrollIntoView = jest.fn();

let mockSearchMode = false;
let mockIncognito = false;
let mockInterruptOnSend = false;
let pending: PendingChatMessage[] = [];
let fetchSpy: jest.SpiedFunction<typeof fetch>;

const mockClearDraft = jest.fn();

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

/** The composer as chat pages mount it, with the session-level queue. */
function ChatInput(inputProps: AppInputBarProps) {
  const queue = useChatSessionQueue(!mockIncognito);
  return <AppInputBar {...inputProps} queue={queue} />;
}

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
  mockInterruptOnSend = false;
  pending = [
    {
      id: "queued",
      message: "Queued follow-up",
      delivery: "queue",
      target_response_id: 2,
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
            has_active_subagents: false,
            has_startable_input: false,
            latest_response_id: 2,
          })
        );
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

test("an accepted message cannot be edited into a duplicate instruction", async () => {
  const user = setupUser();
  render(<ChatInput {...props("streaming")} initialMessage="" />);
  await screen.findByText("Queued follow-up");
  pending = [];
  const textbox = screen.getByRole("textbox", { name: "Message input" });
  await user.click(textbox);
  await user.click(screen.getByRole("button", { name: "Edit queued message" }));
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

test("an accepted send leaves the queue while this browser follows the response", async () => {
  // The jsdom environment has no streams, so the replay body is read by hand.
  const accepted = deferred<ReadableStreamReadResult<Uint8Array>>();
  const ended = deferred<ReadableStreamReadResult<Uint8Array>>();
  const reads = [accepted.promise];
  const replay = {
    ok: true,
    body: {
      getReader: () => ({
        read: () => reads.shift() ?? ended.promise,
        cancel: async () => {},
      }),
    },
  } as unknown as Response;
  const replayStarted = deferred<void>();
  fetchSpy.mockImplementation(async (url) => {
    const path = String(url);
    if (path.includes("resume-stream")) {
      replayStarted.resolve();
      return replay;
    }
    if (path.endsWith("/status"))
      return new Response(
        JSON.stringify({
          is_processing: true,
          current_stream: { stream_id: 2 },
          has_active_subagents: false,
          has_startable_input: false,
          latest_response_id: 2,
        })
      );
    return new Response(JSON.stringify(pending));
  });
  const saved = await fetchSettledChatSession("session");
  jest.mocked(fetchSettledChatSession).mockResolvedValue({
    ...saved,
    messages: [
      {
        message_id: 1,
        message_type: "user",
        message: "Question",
        parent_message: null,
        latest_child_message: 2,
      },
      {
        message_id: 2,
        message_type: "assistant",
        message: "",
        parent_message: 1,
        latest_child_message: null,
      },
    ] as typeof saved.messages,
    packets: [[]],
    is_processing: true,
    current_stream: { stream_id: 2 },
  });
  // The app reads the default SWR cache, which global revalidation reaches.
  render(<ChatInput {...props("input")} initialMessage="" />, {
    swrConfig: { provider: undefined },
  });
  await act(async () => replayStarted.promise);
  expect(screen.getByText("Queued follow-up")).toBeVisible();

  pending = [];
  try {
    await act(async () =>
      accepted.resolve({
        done: false,
        value: new TextEncoder().encode(
          JSON.stringify({
            placement: { turn_index: 1, tab_index: 0 },
            obj: {
              type: "user_message",
              id: "queued",
              message: "Queued follow-up",
            },
          }) + "\n"
        ),
      })
    );
    await waitFor(() =>
      expect(screen.queryByTestId("queued-message-bar")).not.toBeInTheDocument()
    );
  } finally {
    // The response is saved once its replay ends.
    jest.mocked(fetchSettledChatSession).mockResolvedValue(saved);
    await act(async () => ended.resolve({ done: true, value: undefined }));
    // Later tests share the default SWR cache, so let the final reads land.
    await waitFor(() =>
      expect(
        useChatSessionStore.getState().sessions.get("session")?.chatState
      ).toBe("input")
    );
  }
});

test("a server-started turn found by a readiness check clears the input it consumed", async () => {
  let latestResponseId = 2;
  fetchSpy.mockImplementation(async (url) =>
    String(url).endsWith("/status")
      ? new Response(
          JSON.stringify({
            is_processing: false,
            current_stream: null,
            has_active_subagents: false,
            has_startable_input: false,
            latest_response_id: latestResponseId,
          })
        )
      : new Response(JSON.stringify(pending))
  );
  // Earlier tests share the default SWR cache.
  await act(async () => {
    await mutate(() => true, undefined, { revalidate: false });
  });
  // The app reads the default SWR cache, which global revalidation reaches.
  render(<ChatInput {...props("input")} initialMessage="" />, {
    swrConfig: { provider: undefined },
  });
  expect(await screen.findByText("Queued follow-up")).toBeVisible();

  // The queued turn ran to completion between status polls.
  pending = [];
  latestResponseId = 4;
  const { waitForChatResponseEnd: readStatus } = jest.requireActual<
    typeof import("@/lib/chat/sessionReadiness")
  >("@/lib/chat/sessionReadiness");
  await act(async () => {
    await readStatus("session", 2);
  });

  await waitFor(() =>
    expect(screen.queryByTestId("queued-message-bar")).not.toBeInTheDocument()
  );
});

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

test.each([
  [false, "Send", "send"],
  [true, "Interrupt", "interrupt"],
])(
  "the send arrow follows the interrupt preference (interrupt on send: %s)",
  async (interruptOnSend, label, delivery) => {
    mockInterruptOnSend = interruptOnSend;
    const user = setupUser();
    render(<ChatInput {...props("streaming")} />);
    await user.click(screen.getByRole("button", { name: label }));
    await waitFor(() => expect(pending).toHaveLength(2));
    expect(pending[1]).toMatchObject({ message: "Keep this draft", delivery });
  }
);

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
