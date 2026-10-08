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
  useQueryController: () => ({ state: { phase: "idle", appMode: "chat" } }),
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
    clear: jest.fn(),
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
  useChatSessionStore.setState({ sessions: new Map(), currentSessionId: null });
  const store = useChatSessionStore.getState();
  store.createSession("session");
  store.setCurrentSession("session");
  store.enqueueCurrentMessage("Queued follow-up");
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

test("retrying completion preserves the draft and paused queue", async () => {
  const user = setupUser();
  const idle = deferred<void>();
  jest.mocked(waitForChatSessionIdle).mockReturnValue(idle.promise);
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
  const store = useChatSessionStore.getState();
  store.updateSessionData("session", {
    chatState: "unconfirmed",
    queuedMessagesPaused: true,
  });
  const inputProps = props("unconfirmed");
  const { rerender } = render(<AppInputBar {...inputProps} />);
  await user.click(screen.getByRole("button", { name: /Check again$/ }));
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
});
