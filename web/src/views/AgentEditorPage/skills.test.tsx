import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import AgentEditorPage from "@/views/AgentEditorPage/page";
import { createAgent, updateAgent } from "@/lib/agents/svc";
import type { FullAgent } from "@/lib/agents/types";
import type { ToolSnapshot } from "@/lib/tools/types";
import { SKILL_TOOL_ID } from "@/lib/tools/constants";

const mockSkillTool: ToolSnapshot = {
  id: 2000000001,
  name: "read_skill",
  display_name: "Skills",
  description: "Read Skills",
  definition: null,
  custom_headers: null,
  in_code_tool_id: SKILL_TOOL_ID,
  passthrough_auth: false,
  enabled: true,
  chat_selectable: true,
  agent_creation_selectable: true,
  default_enabled: true,
};
const mockRefresh = jest.fn();
const mockOpenAgent = jest.fn();
jest.mock("@/lib/navigation/hooks", () => ({
  useAppPosition: () => ({ openAgent: mockOpenAgent }),
}));
jest.mock("@/lib/agents/hooks", () => ({
  useAgents: () => ({ refresh: mockRefresh }),
  useAgentLabels: () => ({ labels: [], createLabel: jest.fn() }),
}));
jest.mock("@/lib/agents/svc", () => ({
  ...jest.requireActual<typeof import("@/lib/agents/svc")>("@/lib/agents/svc"),
  createAgent: jest.fn(),
  updateAgent: jest.fn(),
}));
jest.mock("@/lib/tools/hooks", () => ({
  useAvailableTools: () => ({ tools: [mockSkillTool], isLoading: false }),
}));
jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({ permissions: [] }),
}));
jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({ vectorDbEnabled: false, appName: "Onyx" }),
}));
jest.mock("@/lib/tiers/hooks", () => ({ useTierAtLeast: () => false }));
jest.mock("@/lib/languageModels/hooks", () => ({
  useLanguageModels: () => ({ llmProviders: [], defaultText: null }),
  useLanguageModelsForAgent: () => ({ llmProviders: [] }),
}));
jest.mock("@/lib/projects/providers", () => ({
  useProjectsContext: () => ({ allRecentFiles: [], beginUpload: jest.fn() }),
}));
jest.mock("@/app/admin/documents/sets/hooks", () => ({
  useDocumentSets: () => ({ data: [] }),
}));
jest.mock("@/lib/mcp/hooks", () => ({
  useMcpServersForAgent: () => ({ mcpServers: [], isLoading: false }),
}));
jest.mock("@/hooks/useOpenApiTools", () => ({
  __esModule: true,
  default: () => ({ openApiTools: [], isLoading: false }),
}));
jest.mock("@/lib/agents/components", () => ({ ShareAgentModal: () => null }));
jest.mock("@/sections/knowledge/AgentKnowledgePane", () => ({
  __esModule: true,
  default: () => null,
}));

const agent: FullAgent = {
  id: 101,
  name: "Report helper",
  description: "A saved Agent",
  tools: [mockSkillTool],
  starter_messages: null,
  document_sets: [],
  is_public: false,
  is_listed: true,
  display_priority: null,
  is_featured: false,
  builtin_persona: false,
  owner: null,
  owner_group: null,
  user_permission: "OWNER",
  user_file_ids: [],
  users: [],
  groups: [],
  system_prompt: null,
  replace_base_system_prompt: false,
  task_prompt: null,
  datetime_aware: false,
  search_start_date: null,
  permissions: {},
  user_shares: [],
  group_shares: [],
  public_permission: "VIEWER",
  sharing_status: "PRIVATE",
  admin_count: 1,
  ownership_vacant: false,
};

beforeEach(() => {
  sessionStorage.clear();
  jest.clearAllMocks();
  jest
    .mocked(createAgent)
    .mockResolvedValue(new Response(JSON.stringify(agent)));
  jest
    .mocked(updateAgent)
    .mockResolvedValue(new Response(JSON.stringify(agent)));
});

test("saving another Agent field preserves its selected Skills tool", async () => {
  const user = setupUser();
  render(<AgentEditorPage agent={agent} />);
  await user.type(screen.getByDisplayValue(agent.name), " updated");
  await user.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() =>
    expect(updateAgent).toHaveBeenCalledWith(
      101,
      expect.objectContaining({ tool_ids: [mockSkillTool.id] })
    )
  );
});

test("the Skills action can be turned off before saving", async () => {
  const user = setupUser();
  render(<AgentEditorPage agent={agent} />);
  const toggle = await screen.findByRole("switch", { name: /Skills/ });
  expect(toggle).toBeChecked();
  await user.click(toggle);
  await user.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() =>
    expect(updateAgent).toHaveBeenCalledWith(
      101,
      expect.objectContaining({ tool_ids: [] })
    )
  );
});

test("the Skills action can be added to an existing Agent", async () => {
  const user = setupUser();
  render(<AgentEditorPage agent={{ ...agent, tools: [] }} />);
  const toggle = await screen.findByRole("switch", { name: /Skills/ });
  expect(toggle).not.toBeChecked();
  await user.click(toggle);
  await user.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() =>
    expect(updateAgent).toHaveBeenCalledWith(
      101,
      expect.objectContaining({ tool_ids: [mockSkillTool.id] })
    )
  );
});
