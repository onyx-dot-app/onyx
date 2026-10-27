import { ChatSessionSharedStatus } from "@/app/app/interfaces";
import {
  act,
  render,
  screen,
  setupUser,
  deferred,
} from "@tests/setup/test-utils";
import AppInputBar, { AppInputBarProps } from "@/sections/input/AppInputBar";
import {
  waitForChatSessionIdle,
  fetchSettledChatSession,
} from "@/lib/chat/sessionReadiness";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";

let mockSearchMode = false;
const mockClearDraft = jest.fn();

jest.mock("@/lib/chat/sessionReadiness", () => ({
  waitForChatSessionIdle: jest.fn(),
  fetchSettledChatSession: jest.fn(),
}));
jest.mock("@/app/app/services/lib", () => ({
  processRawChatHistory: () => new Map(),
}));

jest.mock("@/providers/IncognitoProvider", () => ({
  useIncognito: () => ({ incognitoEnabled: false }),
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
jest.mock("@/lib/position/hooks", () => ({
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
  store.enqueueCurrentMessage("Queued follow-up");
});

test("completion checks stay with their sessions across navigation", async () => {
  const user = setupUser();
  const firstIdle = deferred<void>();
  const secondIdle = deferred<void>();
  jest
    .mocked(waitForChatSessionIdle)
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
  await act(async () => firstIdle.resolve());
  act(() => store.setCurrentSession("other"));
  rerender(<AppInputBar {...props("unconfirmed")} />);
  expect(screen.getByRole("button", { name: /Check again$/ })).toBeDisabled();
  await act(async () => secondIdle.resolve());
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
  expect(
    useChatSessionStore.getState().sessions.get("session")?.queuedMessages
  ).toHaveLength(1);

  act(() =>
    useChatSessionStore
      .getState()
      .setLatestMessageRenderComplete("session", true)
  );
  rerender(<AppInputBar {...inputProps} chatState="input" />);
  expect(inputProps.onSubmit).toHaveBeenCalledWith("Queued follow-up");
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
  expect(
    useChatSessionStore.getState().sessions.get("session")?.queuedMessages
  ).toHaveLength(1);
});

test("a failed save keeps queued messages paused when manual input is available", () => {
  useChatSessionStore
    .getState()
    .updateSessionData("session", { queuedMessagesPaused: true });
  const inputProps = props("cancelling");
  const { rerender } = render(<AppInputBar {...inputProps} />);
  act(() =>
    useChatSessionStore
      .getState()
      .setLatestMessageRenderComplete("session", true)
  );
  rerender(<AppInputBar {...inputProps} chatState="input" />);
  expect(inputProps.onSubmit).not.toHaveBeenCalled();
});

test.each([false, true])(
  "retrying completion preserves the draft and paused queue (failed acknowledgement: %s)",
  async (failedAcknowledgement) => {
    const user = setupUser();
    const idle = deferred<void>();
    jest.mocked(waitForChatSessionIdle).mockReturnValue(idle.promise);

    const store = useChatSessionStore.getState();
    const sendAcknowledged = failedAcknowledgement
      ? Promise.reject(new TypeError("Connection lost before admission"))
      : undefined;
    void sendAcknowledged?.catch(() => {});
    store.updateSessionData("session", {
      chatState: "unconfirmed",
      queuedMessagesPaused: true,
      sendAcknowledged,
    });
    const inputProps = props("unconfirmed");
    const { rerender } = render(<AppInputBar {...inputProps} />);
    await user.click(screen.getByRole("button", { name: /Check again$/ }));
    expect(waitForChatSessionIdle).toHaveBeenCalledWith("session");
    expect(screen.getByRole("button", { name: /Check again$/ })).toBeDisabled();
    expect(inputProps.onSubmit).not.toHaveBeenCalled();
    await act(async () => idle.resolve());
    expect(
      useChatSessionStore.getState().sessions.get("session")?.chatState
    ).toBe("input");
    rerender(<AppInputBar {...inputProps} chatState="input" />);
    expect(
      screen.getByRole("textbox", { name: "Message input" })
    ).toHaveTextContent("Keep this draft");
    expect(
      useChatSessionStore.getState().sessions.get("session")?.queuedMessages
    ).toHaveLength(1);
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
