import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@tests/setup/test-utils";
import BuildChatPanel from "@/app/craft/components/ChatPanel";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import type { BuildLlmSelection } from "@/app/craft/onboarding/constants";

const streamMessage = jest.fn().mockResolvedValue(undefined);
const idle = jest.fn();
jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn() }),
}));
jest.mock("@/lib/analytics/utils", () => ({
  track: jest.fn(),
  AnalyticsEvent: { SENT_CRAFT_MESSAGE: "send" },
}));
jest.mock("@/app/craft/hooks/useBuildStreaming", () => ({
  useBuildStreaming: () => ({
    streamMessage,
    interruptStreaming: idle,
    streamScheduledRunEvents: idle,
    streamTurnEvents: idle,
  }),
}));
jest.mock("@/app/craft/hooks/useWakeOnIntent", () => ({
  useWakeOnIntent: () => idle,
}));
jest.mock("@/app/craft/contexts/UploadFilesContext", () => ({
  UploadFileStatus: { COMPLETED: "completed" },
  useUploadFilesContext: () => ({
    currentMessageFiles: [],
    hasUploadingFiles: false,
    setActiveSession: idle,
    uploadFiles: idle,
  }),
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
  }: {
    disabled: boolean;
    onSubmit: (text: string, files: []) => void;
  }) => (
    <div>
      <button disabled={disabled} onClick={() => onSubmit("prompt", [])}>
        Send
      </button>
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

it("dispatches a completed run's queued prompt without replacing its saved model", async () => {
  const store = useBuildSessionStore.getState();
  store.updateSessionData(SESSION_ID, { status: "running" });
  store.enqueueMessage(SESSION_ID, "queued prompt", []);
  render(<BuildChatPanel existingSessionId={SESSION_ID} />);
  await act(async () =>
    store.updateSessionData(SESSION_ID, { status: "active" })
  );
  await waitFor(() =>
    expect(streamMessage).toHaveBeenCalledWith(
      SESSION_ID,
      "queued prompt",
      null,
      []
    )
  );
  expect(
    useBuildSessionStore.getState().sessions.get(SESSION_ID)?.queuedMessages
  ).toHaveLength(0);
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
