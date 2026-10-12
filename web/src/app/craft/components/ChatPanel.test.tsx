import {
  act,
  deferred,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@tests/setup/test-utils";
import BuildChatPanel from "@/app/craft/components/ChatPanel";
import { useUploadFilesContext } from "@/app/craft/contexts/UploadFilesContext";
import { uploadFile } from "@/app/craft/services/apiServices";
import type { CraftInputBarProps } from "@/app/craft/components/CraftInputBar";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import type { BuildLlmSelection } from "@/app/craft/onboarding/constants";

jest.mock("@/app/craft/services/apiServices", () => ({
  uploadFile: jest.fn(),
}));

const streamMessage = jest.fn().mockResolvedValue(undefined);
const retryQueuedMessage = jest.fn().mockResolvedValue(undefined);
const idle = jest.fn();
jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn() }),
}));
jest.mock("@/lib/analytics/utils", () => ({
  track: jest.fn(),
  AnalyticsEvent: { SENT_CRAFT_MESSAGE: "send" },
}));
jest.mock("@/providers/CraftStreamingProvider", () => ({
  useCraftStreaming: () => ({
    streamMessage,
    retryQueuedMessage,
    interruptStreaming: idle,
    streamScheduledRunEvents: idle,
    streamTurnEvents: idle,
  }),
}));
jest.mock("@/app/craft/hooks/useWakeOnIntent", () => ({
  useWakeOnIntent: () => idle,
}));
jest.mock("@/app/craft/contexts/BuildContext", () => ({
  useBuildContext: () => ({
    setLeftSidebarFolded: idle,
    leftSidebarFolded: false,
    videoBackgroundEnabled: false,
  }),
}));
jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({ user: { id: "user" } }),
}));
jest.mock("@/hooks/useScreenSize", () => ({
  __esModule: true,
  default: () => ({ isMobile: false }),
}));
jest.mock("@/lib/languageModels/hooks", () => ({
  useLanguageModels: () => ({
    llmProviders: [
      {
        id: 1,
        name: "Provider",
        provider: "openai",
        model_configurations: [
          { name: "saved-model", is_visible: true },
          { name: "default-model", is_visible: true },
        ],
      },
    ],
    defaultCraft: { provider_id: 1, model_name: "default-model" },
  }),
}));
jest.mock("@/app/craft/components/CraftInputBar", () => ({
  __esModule: true,
  default: ({
    disabled,
    onSubmit,
    onQueueMessage,
    queuedMessages = [],
    onRemoveQueuedMessage,
  }: Pick<
    CraftInputBarProps,
    | "disabled"
    | "onSubmit"
    | "onQueueMessage"
    | "queuedMessages"
    | "onRemoveQueuedMessage"
  >) => (
    <div>
      <DraftSelection />
      <button disabled={disabled} onClick={() => onSubmit("prompt", [])}>
        Send
      </button>
      <button
        disabled={disabled}
        onClick={() => onQueueMessage?.("queued prompt", [])}
      >
        Queue
      </button>
      {queuedMessages.map((message, index) => (
        <button
          key={message.text}
          onClick={() => onRemoveQueuedMessage?.(index)}
        >
          Remove {message.text}
        </button>
      ))}
    </div>
  ),
}));
jest.mock("@/app/craft/components/ModelPickerButton", () => ({
  __esModule: true,
  default: ({
    selection,
    onChange,
  }: {
    selection: BuildLlmSelection | null;
    onChange: (model: BuildLlmSelection) => void;
  }) => (
    <div data-testid="model-picker">
      {selection?.modelName}
      <button
        onClick={() =>
          onChange({
            providerId: 1,
            providerName: "Provider",
            provider: "openai",
            modelName: "explicit-model",
          })
        }
      >
        Choose model
      </button>
    </div>
  ),
}));
jest.mock("@/app/craft/components/ScheduledRunBanner", () => ({
  __esModule: true,
  default: () => null,
  useScheduledRunContext: () => ({ data: null, mutate: idle }),
}));
jest.mock("@/app/craft/components/BuildMessageList", () => ({
  __esModule: true,
  default: () => <div>Saved history</div>,
}));
jest.mock("@/app/craft/components/BuildWelcome", () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock("@/app/craft/components/AgentSwitcher", () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock("@/app/craft/components/SubagentView", () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock("@/app/craft/components/SandboxStatusIndicator", () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock("@/app/craft/components/SandboxAsleepNotice", () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock("@/app/craft/components/SkillsStaleNotice", () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock("@/app/craft/components/approvals/LiveApprovalsRegion", () => ({
  __esModule: true,
  default: () => null,
}));

function DraftSelection() {
  const { currentMessageFiles, uploadFiles } = useUploadFilesContext();
  return (
    <div>
      <button
        onClick={() => void uploadFiles([new File(["draft"], "draft.txt")])}
      >
        Attach draft
      </button>
      <span data-testid="draft-count">{currentMessageFiles.length}</span>
    </div>
  );
}

const SESSION_ID = "metadata-session";
beforeEach(() => {
  jest.clearAllMocks();
  useBuildSessionStore.setState({
    currentSessionId: null,
    sessions: new Map(),
    preProvisioning: { status: "idle" },
  });
  useBuildSessionStore
    .getState()
    .createSession(SESSION_ID, { status: "active", isLoaded: false });
  useBuildSessionStore.getState().setCurrentSession(SESSION_ID);
});

it("omits display defaults from existing-session sends while metadata loads", async () => {
  render(<BuildChatPanel existingSessionId={SESSION_ID} />);
  expect(screen.getByRole("button", { name: "Send" })).toBeEnabled();
  expect(screen.queryByTestId("model-picker")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() =>
    expect(streamMessage).toHaveBeenCalledWith(SESSION_ID, "prompt", null, [])
  );
  await act(async () =>
    useBuildSessionStore.getState().updateSessionData(SESSION_ID, {
      isLoaded: true,
      agentProvider: "openai",
      agentModel: "saved-model",
    })
  );
  expect(screen.getByTestId("model-picker")).toHaveTextContent("saved-model");
});

it("shows a failed metadata load and retries the session explicitly", async () => {
  const original = useBuildSessionStore.getState().loadSession;
  const loadSession = jest.fn().mockResolvedValue(undefined);
  useBuildSessionStore.setState({ loadSession });
  useBuildSessionStore
    .getState()
    .updateSessionData(SESSION_ID, { loadError: "Runtime unavailable" });
  try {
    render(<BuildChatPanel existingSessionId={SESSION_ID} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Runtime unavailable");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(loadSession).toHaveBeenCalledWith(SESSION_ID, { force: true });
  } finally {
    await act(async () =>
      useBuildSessionStore.setState({ loadSession: original })
    );
  }
});

it("leaves queue dispatch to the session lifecycle when the displayed status changes", async () => {
  const store = useBuildSessionStore.getState();
  store.updateSessionData(SESSION_ID, { status: "running" });
  store.enqueueMessage(SESSION_ID, "queued prompt", []);
  render(<BuildChatPanel existingSessionId={SESSION_ID} />);
  await act(async () =>
    store.updateSessionData(SESSION_ID, { status: "active" })
  );
  expect(streamMessage).not.toHaveBeenCalled();
  expect(
    useBuildSessionStore.getState().sessions.get(SESSION_ID)?.queuedMessages
  ).toHaveLength(1);
});

it("offers explicit retry for a rejected queued prompt without reloading history", () => {
  const store = useBuildSessionStore.getState();
  store.enqueueMessage(SESSION_ID, "queued prompt", []);
  store.updateSessionData(SESSION_ID, {
    status: "failed",
    error: "Send rejected",
    queuedMessages: (
      useBuildSessionStore.getState().sessions.get(SESSION_ID)
        ?.queuedMessages ?? []
    ).map((message) => ({ ...message, phase: "failed" })),
  });
  render(<BuildChatPanel existingSessionId={SESSION_ID} />);
  expect(screen.getByRole("alert")).toHaveTextContent("Send rejected");
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(retryQueuedMessage).toHaveBeenCalledWith(SESSION_ID);
  expect(
    useBuildSessionStore.getState().sessions.get(SESSION_ID)?.queuedMessages
  ).toHaveLength(1);
});

it("retries failed settlement through its owner without replacing it with a session reload", async () => {
  const original = useBuildSessionStore.getState().retryTurnSettlement;
  const retryTurnSettlement = jest.fn().mockResolvedValue(undefined);
  useBuildSessionStore.setState({ retryTurnSettlement });
  useBuildSessionStore.getState().updateSessionData(SESSION_ID, {
    turnSettlement: {
      owner: { kind: "interactive", turnId: "completed" },
      turnGeneration: 0,
      phase: "failed",
      error: "History unavailable",
    },
    loadError: "Runtime unavailable",
  });
  try {
    render(<BuildChatPanel existingSessionId={SESSION_ID} />);
    expect(screen.getByRole("alert")).toHaveTextContent("History unavailable");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(retryTurnSettlement).toHaveBeenCalledWith(SESSION_ID);
    expect(retryQueuedMessage).not.toHaveBeenCalled();
  } finally {
    await act(async () =>
      useBuildSessionStore.setState({ retryTurnSettlement: original })
    );
  }
});

it("keeps queued prompts when interrupted history fails to reload", async () => {
  const store = useBuildSessionStore.getState();
  store.updateSessionData(SESSION_ID, {
    status: "running",
    isInterrupting: true,
  });
  store.enqueueMessage(SESSION_ID, "queued prompt", []);
  render(<BuildChatPanel existingSessionId={SESSION_ID} />);
  await act(async () =>
    store.updateSessionData(SESSION_ID, {
      status: "active",
      isInterrupting: false,
      loadError: "History unavailable",
    })
  );
  expect(streamMessage).not.toHaveBeenCalled();
  expect(
    useBuildSessionStore.getState().sessions.get(SESSION_ID)?.queuedMessages
  ).toHaveLength(1);
  expect(screen.getByRole("alert")).toHaveTextContent("History unavailable");
});

it("sends a model override when the user explicitly changes the picker", async () => {
  useBuildSessionStore.getState().updateSessionData(SESSION_ID, {
    isLoaded: true,
    agentProvider: "openai",
    agentModel: "saved-model",
  });
  render(<BuildChatPanel existingSessionId={SESSION_ID} />);
  fireEvent.click(screen.getByRole("button", { name: "Choose model" }));
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() =>
    expect(streamMessage).toHaveBeenCalledWith(
      SESSION_ID,
      "prompt",
      expect.objectContaining({ modelName: "explicit-model" }),
      []
    )
  );
});

it("captures an explicit model choice with the queued prompt", () => {
  useBuildSessionStore.getState().updateSessionData(SESSION_ID, {
    isLoaded: true,
    status: "running",
    agentProvider: "openai",
    agentModel: "saved-model",
  });
  render(<BuildChatPanel existingSessionId={SESSION_ID} />);
  fireEvent.click(screen.getByRole("button", { name: "Choose model" }));
  fireEvent.click(screen.getByRole("button", { name: "Queue" }));
  expect(
    useBuildSessionStore.getState().sessions.get(SESSION_ID)?.queuedMessages[0]
      ?.model
  ).toEqual(expect.objectContaining({ modelName: "explicit-model" }));
});

it("removes the displayed waiting prompt without removing a starting head", () => {
  const store = useBuildSessionStore.getState();
  store.enqueueMessage(SESSION_ID, "starting", []);
  store.enqueueMessage(SESSION_ID, "waiting", []);
  store.enqueueMessage(SESSION_ID, "last", []);
  store.updateSessionData(SESSION_ID, {
    turnSettlement: {
      owner: { kind: "interactive", turnId: "completed" },
      turnGeneration: 0,
      phase: "ready",
    },
  });
  store.claimQueuedMessage(SESSION_ID);
  render(<BuildChatPanel existingSessionId={SESSION_ID} />);
  expect(
    screen.queryByRole("button", { name: "Remove starting" })
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Remove waiting" }));
  expect(
    useBuildSessionStore
      .getState()
      .sessions.get(SESSION_ID)
      ?.queuedMessages.map((message) => message.text)
  ).toEqual(["starting", "last"]);
});

it("does not offer queue retry for a different prompt's failure", () => {
  const store = useBuildSessionStore.getState();
  store.enqueueMessage(SESSION_ID, "waiting prompt", []);
  store.updateSessionData(SESSION_ID, {
    status: "failed",
    error: "Original prompt rejected",
  });
  render(<BuildChatPanel existingSessionId={SESSION_ID} />);
  expect(
    screen.queryByRole("button", { name: "Try again" })
  ).not.toBeInTheDocument();
  expect(retryQueuedMessage).not.toHaveBeenCalled();
  expect(
    useBuildSessionStore.getState().sessions.get(SESSION_ID)?.queuedMessages[0]
  ).toMatchObject({ text: "waiting prompt", phase: "waiting" });
});

it("retains a draft on rerender and starts fresh after chat unmounts", async () => {
  const upload = jest.mocked(uploadFile).mockResolvedValue({
    path: "attachments/draft.txt",
    filename: "draft.txt",
    size_bytes: 5,
  });
  const first = render(<BuildChatPanel existingSessionId={SESSION_ID} />);
  fireEvent.click(screen.getByRole("button", { name: "Attach draft" }));
  await waitFor(() => expect(upload).toHaveBeenCalledTimes(1));
  first.rerender(<BuildChatPanel existingSessionId={SESSION_ID} />);
  expect(screen.getByTestId("draft-count")).toHaveTextContent("1");
  first.unmount();
  render(<BuildChatPanel existingSessionId={SESSION_ID} />);
  expect(screen.getByTestId("draft-count")).toHaveTextContent("0");
});

it("cannot restore a draft when an old chat upload completes after remount", async () => {
  const pending = deferred<Awaited<ReturnType<typeof uploadFile>>>();
  const upload = jest.mocked(uploadFile).mockReturnValue(pending.promise);
  const first = render(<BuildChatPanel existingSessionId={SESSION_ID} />);
  fireEvent.click(screen.getByRole("button", { name: "Attach draft" }));
  expect(screen.getByTestId("draft-count")).toHaveTextContent("1");
  first.unmount();
  render(<BuildChatPanel existingSessionId={SESSION_ID} />);
  await act(async () =>
    pending.resolve({
      path: "attachments/draft.txt",
      filename: "draft.txt",
      size_bytes: 5,
    })
  );
  expect(screen.getByTestId("draft-count")).toHaveTextContent("0");
  expect(upload).toHaveBeenCalledTimes(1);
});

it("holds submission during restoration and enables it when the sandbox is ready", async () => {
  const store = useBuildSessionStore.getState();
  store.updateSessionData(SESSION_ID, { status: "creating" });
  render(<BuildChatPanel existingSessionId={SESSION_ID} />);
  expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Queue" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Queue" }));
  expect(
    useBuildSessionStore.getState().sessions.get(SESSION_ID)?.queuedMessages
  ).toHaveLength(0);
  await act(async () =>
    store.updateSessionData(SESSION_ID, { status: "active" })
  );
  expect(screen.getByRole("button", { name: "Send" })).toBeEnabled();
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
  expect(streamMessage).toHaveBeenCalledWith(SESSION_ID, "prompt", null, []);
});

it("keeps queueing available while an interactive start is pending", () => {
  useBuildSessionStore.getState().updateSessionData(SESSION_ID, {
    status: "creating",
    activeTurnLocalOwner: true,
  });
  render(<BuildChatPanel existingSessionId={SESSION_ID} />);
  expect(screen.getByRole("button", { name: "Queue" })).toBeEnabled();
  fireEvent.click(screen.getByRole("button", { name: "Queue" }));
  expect(
    useBuildSessionStore.getState().sessions.get(SESSION_ID)?.queuedMessages
  ).toHaveLength(1);
});
