import { render, screen, setupUser } from "@tests/setup/test-utils";
import { act, createRef } from "react";
import AppInputBar, {
  type AppInputBarHandle,
} from "@/sections/input/AppInputBar";
import { type ProjectFile, UserFileStatus } from "@/lib/projects/types";
import { ChatFileType, type ChatState } from "@/app/app/interfaces";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import { useLlmManager } from "@/lib/hooks";
import { useToolConfiguration } from "@/lib/tools/hooks";
import type { MinimalAgent } from "@/lib/agents/types";
import type { MemberPlugin } from "@/lib/plugins/member";
import { Button } from "@opal/components";
import {
  memberServer,
  storedMcpTool,
} from "@/sections/plugins/__tests__/memberPluginFixtures";

jest.mock("@/lib/hooks", () => ({
  useLlmManager: () => ({ isLoadingProviders: true }),
}));
jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({ user: null, isAdmin: false }),
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
const mockVoiceStatus = { sttEnabled: false };
jest.mock("@/hooks/useVoiceStatus", () => ({
  useVoiceStatus: () => mockVoiceStatus,
}));
// Stands in for the recorder: one click delivers a finished transcription.
jest.mock("@/sections/input/MicrophoneButton", () => ({
  __esModule: true,
  default: ({ onAutoSend }: { onAutoSend: (text: string) => void }) => (
    <Button onClick={() => onAutoSend("spoken message")}>
      Auto-send voice
    </Button>
  ),
}));
jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({ appName: "Onyx" }),
}));
jest.mock("@/lib/position/hooks", () => ({
  useAppPosition: () => ({
    isNewSession: () => true,
    chat: () => null,
    agent: () => null,
    project: () => null,
  }),
}));
jest.mock("@/lib/agents/hooks", () => ({ useActiveAgent: () => undefined }));
const mockProjectsContext: {
  currentMessageFiles: ProjectFile[];
  setCurrentMessageFiles: jest.Mock;
} = { currentMessageFiles: [], setCurrentMessageFiles: jest.fn() };
jest.mock("@/lib/projects/providers", () => ({
  useProjectsContext: () => mockProjectsContext,
}));
jest.mock("@/lib/projects/hooks", () => ({
  ...jest.requireActual("@/lib/projects/hooks"),
  useProjects: () => ({ isLoading: false }),
  useActiveProject: () => null,
}));
jest.mock("@/lib/connectors/hooks", () => ({
  useAvailableSources: () => ({ isLoading: true }),
}));
jest.mock("@/hooks/usePromptShortcuts", () => ({
  __esModule: true,
  default: () => ({ activePromptShortcuts: [] }),
}));
jest.mock("@/refresh-components/popovers/FilePickerPopover", () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock("@/lib/tools/components", () => ({ ToolsPopover: () => null }));

const agent: MinimalAgent = {
  id: 0,
  name: "Default Chat",
  description: "",
  tools: [storedMcpTool],
  starter_messages: null,
  document_sets: [],
  is_public: true,
  is_listed: true,
  display_priority: null,
  is_featured: false,
  builtin_persona: true,
  owner: null,
  owner_group: null,
  user_permission: "VIEWER",
};

const plugin: MemberPlugin = {
  kind: "mcp",
  server: memberServer(),
  tools: [storedMcpTool],
  connection: { kind: "connected", ownership: "user" },
};

function Composer({
  plugins,
  agentId = 0,
  inputBarRef,
  availableContextTokens,
  onSubmit = jest.fn(),
  chatState = "input",
}: {
  plugins: readonly MemberPlugin[];
  agentId?: number;
  inputBarRef?: React.Ref<AppInputBarHandle>;
  availableContextTokens?: number;
  onSubmit?: (message: string) => void;
  chatState?: ChatState;
}) {
  const configuration = useToolConfiguration(agentId);
  const llmManager = useLlmManager();
  return (
    <>
      <Button
        onClick={() =>
          configuration.setToolState(storedMcpTool.id, () => "forced")
        }
      >
        Force selected tool
      </Button>
      <output aria-label="Stored forced tool">
        {configuration.forcedToolId}
      </output>
      <AppInputBar
        ref={inputBarRef}
        activeAgent={{ ...agent, id: agentId }}
        memberPlugins={plugins}
        toolConfiguration={configuration}
        llmManager={llmManager}
        stopGenerating={jest.fn()}
        onSubmit={onSubmit}
        handleFileUpload={jest.fn()}
        deepResearchEnabled={false}
        toggleDeepResearch={jest.fn()}
        chatState={chatState}
        availableContextTokens={availableContextTokens}
        disabled={false}
      />
    </>
  );
}

beforeEach(() => {
  localStorage.clear();
  mockProjectsContext.currentMessageFiles = [];
  mockProjectsContext.setCurrentMessageFiles.mockClear();
  mockVoiceStatus.sttEnabled = false;
  useChatSessionStore.setState({
    currentSessionId: null,
    sessions: new Map(),
  });
});

test("default Chat hides the forced plugin pill until metadata confirms availability without clearing the selection", async () => {
  const { rerender } = render(<Composer plugins={[]} />);
  await setupUser().click(
    screen.getByRole("button", { name: "Force selected tool" })
  );
  expect(screen.getByLabelText("Stored forced tool")).toHaveTextContent(
    String(storedMcpTool.id)
  );
  expect(
    screen.queryByRole("button", { name: storedMcpTool.display_name })
  ).not.toBeInTheDocument();
  rerender(<Composer plugins={[plugin]} />);
  expect(
    screen.getByRole("button", { name: storedMcpTool.display_name })
  ).toBeVisible();
  rerender(
    <Composer
      plugins={[
        {
          ...plugin,
          server: { ...plugin.server, user_enabled_in_chat: false },
        },
      ]}
    />
  );
  expect(
    screen.queryByRole("button", { name: storedMcpTool.display_name })
  ).not.toBeInTheDocument();
  expect(screen.getByLabelText("Stored forced tool")).toHaveTextContent(
    String(storedMcpTool.id)
  );
});

test("custom agents retain the forced plugin pill without member metadata", async () => {
  render(<Composer plugins={[]} agentId={8} />);
  await setupUser().click(
    screen.getByRole("button", { name: "Force selected tool" })
  );
  expect(
    screen.getByRole("button", { name: storedMcpTool.display_name })
  ).toBeVisible();
});

describe("restore after a failed send", () => {
  function projectFile(id: string): ProjectFile {
    return {
      id,
      name: `${id}.txt`,
      project_id: null,
      user_id: null,
      file_id: `${id}-file-id`,
      created_at: "2026-01-01T00:00:00Z",
      status: UserFileStatus.COMPLETED,
      file_type: "text/plain",
      last_accessed_at: "2026-01-01T00:00:00Z",
      chat_file_type: ChatFileType.PLAIN_TEXT,
      token_count: null,
      chunk_count: null,
    };
  }
  const failedFiles = [projectFile("failed-file")] satisfies ProjectFile[];

  test("puts the message and files back into an empty composer", () => {
    const inputBarRef = createRef<AppInputBarHandle>();
    render(<Composer plugins={[]} inputBarRef={inputBarRef} />);
    act(() => inputBarRef.current?.restore("failed message", failedFiles));
    expect(screen.getByRole("textbox")).toHaveTextContent("failed message");
    expect(mockProjectsContext.setCurrentMessageFiles).toHaveBeenCalledWith(
      failedFiles
    );
  });

  test("keeps text typed while the send was pending", async () => {
    const inputBarRef = createRef<AppInputBarHandle>();
    render(<Composer plugins={[]} inputBarRef={inputBarRef} />);
    await setupUser().type(screen.getByRole("textbox"), "newer draft");
    act(() => inputBarRef.current?.restore("failed message", failedFiles));
    expect(screen.getByRole("textbox")).toHaveTextContent("newer draft");
    expect(screen.getByRole("textbox")).not.toHaveTextContent("failed message");
    expect(mockProjectsContext.setCurrentMessageFiles).not.toHaveBeenCalled();
  });

  test("keeps files attached while the send was pending", () => {
    mockProjectsContext.currentMessageFiles = [
      projectFile("newer-file"),
    ] satisfies ProjectFile[];
    const inputBarRef = createRef<AppInputBarHandle>();
    render(<Composer plugins={[]} inputBarRef={inputBarRef} />);
    act(() => inputBarRef.current?.restore("failed message", failedFiles));
    expect(screen.getByRole("textbox")).not.toHaveTextContent("failed message");
    expect(mockProjectsContext.setCurrentMessageFiles).not.toHaveBeenCalled();
  });
});

describe("attached files still indexing", () => {
  function processingFile(tokenCount: number): ProjectFile {
    return {
      id: "processing-file",
      name: "report.pdf",
      project_id: null,
      user_id: null,
      file_id: "processing-file-id",
      created_at: "2026-01-01T00:00:00Z",
      status: UserFileStatus.PROCESSING,
      file_type: "application/pdf",
      last_accessed_at: "2026-01-01T00:00:00Z",
      chat_file_type: ChatFileType.DOCUMENT,
      token_count: tokenCount,
      chunk_count: null,
    };
  }

  test("sends right away when the files fit in the context", async () => {
    mockProjectsContext.currentMessageFiles = [processingFile(1_000)];
    const onSubmit = jest.fn();
    render(
      <Composer
        plugins={[]}
        availableContextTokens={10_000}
        onSubmit={onSubmit}
      />
    );
    await setupUser().type(screen.getByRole("textbox"), "summarize{Enter}");
    expect(onSubmit).toHaveBeenCalledWith("summarize");
    expect(
      screen.queryByText("File is too large for the chat")
    ).not.toBeInTheDocument();
  });

  test("waits for indexing and shows a closable banner when files do not fit", async () => {
    mockProjectsContext.currentMessageFiles = [processingFile(9_000)];
    const onSubmit = jest.fn();
    render(
      <Composer
        plugins={[]}
        availableContextTokens={10_000}
        onSubmit={onSubmit}
      />
    );
    expect(screen.getByText("File is too large for the chat")).toBeVisible();

    const user = setupUser();
    await user.type(screen.getByRole("textbox"), "summarize{Enter}");
    expect(onSubmit).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(
      screen.queryByText("File is too large for the chat")
    ).not.toBeInTheDocument();
    await user.keyboard("{Enter}");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  test("shows the banner again when a different set of files blocks send", async () => {
    mockProjectsContext.currentMessageFiles = [processingFile(9_000)];
    const { rerender } = render(
      <Composer plugins={[]} availableContextTokens={10_000} />
    );
    await setupUser().click(screen.getByRole("button", { name: "Close" }));
    expect(
      screen.queryByText("File is too large for the chat")
    ).not.toBeInTheDocument();

    mockProjectsContext.currentMessageFiles = [
      processingFile(9_000),
      { ...processingFile(1_000), id: "second-file" },
    ];
    rerender(<Composer plugins={[]} availableContextTokens={10_000} />);
    expect(screen.getByText("File is too large for the chat")).toBeVisible();
  });

  test("voice auto-send waits for files that block send", async () => {
    mockVoiceStatus.sttEnabled = true;
    mockProjectsContext.currentMessageFiles = [processingFile(9_000)];
    const onSubmit = jest.fn();
    render(
      <Composer
        plugins={[]}
        availableContextTokens={10_000}
        onSubmit={onSubmit}
      />
    );
    await setupUser().click(
      screen.getByRole("button", { name: "Auto-send voice" })
    );
    expect(onSubmit).not.toHaveBeenCalled();
  });

  test("holds a queued message until the files finish indexing", () => {
    act(() => {
      useChatSessionStore.getState().setCurrentSession("session-1");
      useChatSessionStore.getState().enqueueMessage("session-1", "queued");
    });
    mockProjectsContext.currentMessageFiles = [processingFile(9_000)];
    const onSubmit = jest.fn();
    const composer = (chatState: ChatState) => (
      <Composer
        plugins={[]}
        availableContextTokens={10_000}
        onSubmit={onSubmit}
        chatState={chatState}
      />
    );
    const { rerender } = render(composer("streaming"));

    rerender(composer("input"));
    expect(onSubmit).not.toHaveBeenCalled();

    mockProjectsContext.currentMessageFiles = [
      { ...processingFile(9_000), status: UserFileStatus.COMPLETED },
    ];
    rerender(composer("input"));
    expect(onSubmit).toHaveBeenCalledWith("queued");
  });

  test("waits for a file with no extracted text yet", () => {
    mockProjectsContext.currentMessageFiles = [processingFile(0)];
    render(<Composer plugins={[]} availableContextTokens={10_000} />);
    expect(screen.getByText("File is still being read")).toBeVisible();
  });
});
