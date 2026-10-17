import { render, screen, setupUser } from "@tests/setup/test-utils";
import AppInputBar from "@/sections/input/AppInputBar";
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
jest.mock("@/hooks/useVoiceStatus", () => ({
  useVoiceStatus: () => ({ sttEnabled: false }),
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
jest.mock("@/lib/projects/providers", () => ({
  useProjectsContext: () => ({ currentMessageFiles: [] }),
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
}: {
  plugins: readonly MemberPlugin[];
  agentId?: number;
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
        activeAgent={{ ...agent, id: agentId }}
        memberPlugins={plugins}
        toolConfiguration={configuration}
        llmManager={llmManager}
        stopGenerating={jest.fn()}
        onSubmit={jest.fn()}
        handleFileUpload={jest.fn()}
        deepResearchEnabled={false}
        toggleDeepResearch={jest.fn()}
        chatState="input"
        disabled={false}
      />
    </>
  );
}

beforeEach(() => localStorage.clear());

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
