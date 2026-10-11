import {
  act,
  deferred,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@tests/setup/test-utils";
import BuildChatPanel from "@/app/craft/components/ChatPanel";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import { useUploadFilesContext } from "@/app/craft/contexts/UploadFilesContext";
import { uploadFile } from "@/app/craft/services/apiServices";
jest.mock("@/app/craft/services/apiServices", () => ({
  uploadFile: jest.fn(),
}));

const idle = jest.fn();

jest.mock("next/navigation", () => ({ useRouter: () => ({ push: idle }) }));
jest.mock("@/lib/analytics/utils", () => ({
  track: jest.fn(),
  AnalyticsEvent: {},
}));
jest.mock("@/app/craft/hooks/useBuildStreaming", () => ({
  useBuildStreaming: () => ({
    streamMessage: idle,
    interruptStreaming: idle,
    streamScheduledRunEvents: idle,
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
  useLanguageModels: () => ({ llmProviders: [] }),
}));
jest.mock("@/app/craft/components/CraftInputBar", () => ({
  __esModule: true,
  default: function DraftInput() {
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
  },
}));
jest.mock("@/app/craft/components/ModelPickerButton", () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock("@/app/craft/components/ScheduledRunBanner", () => ({
  __esModule: true,
  default: () => null,
  useScheduledRunContext: () => ({ data: null, mutate: idle }),
}));
jest.mock("@/app/craft/components/BuildMessageList", () => ({
  __esModule: true,
  default: () => null,
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

beforeEach(() => {
  jest.clearAllMocks();
  jest.mocked(uploadFile).mockResolvedValue({
    path: "attachments/draft.txt",
    filename: "draft.txt",
    size_bytes: 5,
  });
  useBuildSessionStore.setState({
    currentSessionId: null,
    sessions: new Map(),
    preProvisioning: { status: "idle" },
  });
  useBuildSessionStore
    .getState()
    .createSession("session", { status: "active", isLoaded: false });
  useBuildSessionStore.getState().setCurrentSession("session");
});

it("retains a draft on rerender and starts fresh after chat unmounts", async () => {
  const first = render(<BuildChatPanel existingSessionId="session" />);
  fireEvent.click(screen.getByRole("button", { name: "Attach draft" }));
  await waitFor(() => expect(uploadFile).toHaveBeenCalledTimes(1));
  first.rerender(<BuildChatPanel existingSessionId="session" />);
  expect(screen.getByTestId("draft-count")).toHaveTextContent("1");
  first.unmount();
  render(<BuildChatPanel existingSessionId="session" />);
  expect(screen.getByTestId("draft-count")).toHaveTextContent("0");
});

it("cannot restore a draft when an old chat upload completes after remount", async () => {
  const upload = deferred<Awaited<ReturnType<typeof uploadFile>>>();
  jest.mocked(uploadFile).mockReturnValue(upload.promise);
  const first = render(<BuildChatPanel existingSessionId="session" />);
  fireEvent.click(screen.getByRole("button", { name: "Attach draft" }));
  expect(screen.getByTestId("draft-count")).toHaveTextContent("1");
  first.unmount();
  render(<BuildChatPanel existingSessionId="session" />);
  await act(async () =>
    upload.resolve({
      path: "attachments/draft.txt",
      filename: "draft.txt",
      size_bytes: 5,
    })
  );
  expect(screen.getByTestId("draft-count")).toHaveTextContent("0");
  expect(uploadFile).toHaveBeenCalledTimes(1);
});
