import { render, screen, setupUser } from "@tests/setup/test-utils";
import { act, createRef } from "react";
import AppInputBar, {
  type AppInputBarHandle,
} from "@/sections/input/AppInputBar";
import { type ProjectFile, UserFileStatus } from "@/lib/projects/types";
import { ChatFileType } from "@/app/app/types";
import { useLlmManager } from "@/lib/hooks";
import { useToolConfiguration } from "@/lib/tools/hooks";
import { useChatSessionQueue } from "@/lib/chat/hooks";
import type { MinimalAgent } from "@/lib/agents/types";
import type { MemberPlugin } from "@/lib/plugins/member";
import { Button } from "@opal/components";
import {
  memberServer,
  memberTool,
  storedMcpTool,
} from "@/sections/plugins/__tests__/memberPluginFixtures";
import { SEARCH_TOOL_ID } from "@/lib/tools/constants";
import type { ChatState } from "@/app/app/types";

jest.mock("@/lib/hooks", () => ({
  useLlmManager: () => ({ isLoadingProviders: true }),
}));
jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({ user: null, isAdmin: false }),
}));
let mockIncognitoEnabled = false;
jest.mock("@/providers/IncognitoProvider", () => ({
  useIncognito: () => ({ incognitoEnabled: mockIncognitoEnabled }),
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
jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({ appName: "Onyx" }),
}));
jest.mock("next/navigation", () => ({
  ...jest.requireActual<typeof import("@tests/setup/mocks/nextNavigation")>(
    "@tests/setup/mocks/nextNavigation"
  ).nextNavigationMock,
  useRouter: () => ({}),
}));
jest.mock("@/lib/navigation/hooks", () => ({
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
  tools = agent.tools,
  inputBarRef,
  chatState = "input",
  disabled = false,
}: {
  plugins: readonly MemberPlugin[];
  agentId?: number;
  tools?: MinimalAgent["tools"];
  inputBarRef?: React.Ref<AppInputBarHandle>;
  chatState?: ChatState;
  disabled?: boolean;
}) {
  const configuration = useToolConfiguration(agentId);
  const llmManager = useLlmManager();
  const queue = useChatSessionQueue(false);
  return (
    <>
      <Button
        onClick={() =>
          configuration.setToolState(storedMcpTool.id, () => "preferred")
        }
      >
        Prefer selected tool
      </Button>
      <output aria-label="Stored preferred tool">
        {configuration.preferredToolId}
      </output>
      <AppInputBar
        ref={inputBarRef}
        activeAgent={{ ...agent, id: agentId, tools }}
        memberPlugins={plugins}
        toolConfiguration={configuration}
        llmManager={llmManager}
        stopGenerating={jest.fn()}
        onSubmit={jest.fn()}
        handleFileUpload={jest.fn()}
        deepResearchEnabled={false}
        toggleDeepResearch={jest.fn()}
        chatState={chatState}
        disabled={disabled}
        queue={queue}
      />
    </>
  );
}

beforeEach(() => {
  localStorage.clear();
  mockIncognitoEnabled = false;
  mockProjectsContext.currentMessageFiles = [];
  mockProjectsContext.setCurrentMessageFiles.mockClear();
});

test("default Chat hides the preferred plugin pill until metadata confirms availability without clearing the selection", async () => {
  const { rerender } = render(<Composer plugins={[]} />);
  await setupUser().click(
    screen.getByRole("button", { name: "Prefer selected tool" })
  );
  expect(screen.getByLabelText("Stored preferred tool")).toHaveTextContent(
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
  expect(screen.getByLabelText("Stored preferred tool")).toHaveTextContent(
    String(storedMcpTool.id)
  );
});

test("custom agents retain the preferred plugin pill without member metadata", async () => {
  render(<Composer plugins={[]} agentId={8} />);
  await setupUser().click(
    screen.getByRole("button", { name: "Prefer selected tool" })
  );
  expect(
    screen.getByRole("button", { name: storedMcpTool.display_name })
  ).toBeVisible();
});

test("incognito greys out Deep Research and explains why", async () => {
  mockIncognitoEnabled = true;
  render(
    <Composer
      plugins={[]}
      tools={[memberTool({ id: 1, in_code_tool_id: SEARCH_TOOL_ID })]}
    />
  );
  const button = screen.getByRole("button", { name: "Deep Research" });
  expect(button).toBeDisabled();
  await setupUser().hover(button);
  expect(await screen.findByRole("tooltip")).toHaveTextContent(
    "Deep Research isn't available in incognito mode"
  );
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

test.each([
  ["input", false, "true"],
  ["streaming", false, "false"],
  ["cancelling", false, "false"],
  ["input", true, "false"],
] as const)(
  "the composer accepts a normal send only when idle and enabled (%s, disabled=%s)",
  (chatState, disabled, accepts) => {
    const { container } = render(
      <Composer plugins={[]} chatState={chatState} disabled={disabled} />
    );
    expect(container.querySelector("#onyx-chat-input")).toHaveAttribute(
      "data-accepts-send",
      accepts
    );
  }
);
