import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { FullPersona } from "@/app/admin/agents/interfaces";
import { updatePersona } from "@/app/admin/agents/lib";
import { HierarchyNodeDocumentsResponse } from "@/lib/hierarchy/interfaces";
import {
  fetchHierarchyNodes,
  fetchHierarchyNodeDocuments,
} from "@/lib/hierarchy/svc";
import { ValidSources } from "@/lib/types";
import AgentEditorPage from "@/refresh-pages/AgentEditorPage";

jest.mock("next/navigation", () => ({
  useRouter: () => ({ back: jest.fn() }),
  usePathname: () => "/admin/agents/1",
  useSearchParams: () => new URLSearchParams(),
}));
jest.mock("@/hooks/appNavigation", () => ({ useAppRouter: () => jest.fn() }));
jest.mock("@/hooks/useAgents", () => ({
  useAgents: () => ({ refresh: jest.fn() }),
}));
jest.mock("@/providers/ProjectsContext", () => ({
  useProjectsContext: () => ({ allRecentFiles: [], beginUpload: jest.fn() }),
}));
jest.mock("@/providers/SettingsProvider", () => ({
  useVectorDbEnabled: () => true,
}));
jest.mock("@/app/admin/documents/sets/hooks", () => ({
  useDocumentSets: () => ({ data: [] }),
}));
jest.mock("@/hooks/useMcpServersForAgentEditor", () => ({
  __esModule: true,
  default: () => ({ mcpData: { mcp_servers: [] }, isLoading: false }),
}));
jest.mock("@/hooks/useOpenApiTools", () => ({
  __esModule: true,
  default: () => ({ openApiTools: [], isLoading: false }),
}));
jest.mock("@/hooks/useLLMProviders", () => ({
  useLLMProviders: () => ({ llmProviders: [] }),
}));
jest.mock("@/hooks/useAvailableTools", () => ({
  useAvailableTools: () => ({ tools: [], isLoading: false }),
}));
jest.mock("@/hooks/useCCPairs", () => ({
  __esModule: true,
  default: () => ({ ccPairs: [{ source: "canvas" }] }),
}));
jest.mock("@/components/settings/usePaidEnterpriseFeaturesEnabled", () => ({
  usePaidEnterpriseFeaturesEnabled: () => false,
}));
jest.mock("@/components/llm/LLMSelector", () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock("@/components/modals/UserFilesModal", () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock("@/sections/modals/ShareAgentModal", () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock("@/hooks/useToast", () => ({
  toast: { success: jest.fn(), error: jest.fn() },
}));
jest.mock("@/app/admin/agents/lib");
jest.mock("@/lib/hierarchy/svc");

const agent: FullPersona = {
  id: 1,
  name: "Knowledge agent",
  description: "",
  tools: [],
  starter_messages: null,
  document_sets: [],
  is_public: false,
  is_listed: false,
  display_priority: null,
  is_featured: false,
  builtin_persona: false,
  owner: null,
  user_file_ids: [],
  users: [],
  groups: [],
  system_prompt: null,
  replace_base_system_prompt: false,
  task_prompt: null,
  datetime_aware: false,
  search_start_date: null,
  hierarchy_nodes: [
    {
      id: 1,
      raw_node_id: "course",
      display_name: "Course materials",
      link: null,
      source: ValidSources.Canvas,
      node_type: "folder",
    },
  ],
};

function documentPage(
  parentId: number,
  more = false
): HierarchyNodeDocumentsResponse {
  return {
    documents: [
      {
        id: `document-${parentId}`,
        title: `File in folder ${parentId}`,
        parent_id: parentId,
        link: null,
        last_modified: null,
        last_synced: null,
      },
    ],
    next_cursor: more ? { document_id: `document-${parentId}` } : null,
    page_size: 100,
    sort_field: "name",
    sort_direction: "asc",
    folder_position: "on_top",
  };
}

async function clickButton(name: string) {
  await act(async () => {
    fireEvent.click(await screen.findByRole("button", { name }));
  });
}

async function startPendingSelection() {
  jest.mocked(fetchHierarchyNodes).mockResolvedValue({
    nodes: [
      { id: 1, title: "Course materials", parent_id: null, link: null },
      { id: 2, title: "Week 1", parent_id: 1, link: null },
      { id: 3, title: "Week 2", parent_id: 1, link: null },
    ],
  });
  jest
    .mocked(fetchHierarchyNodeDocuments)
    .mockImplementation(async (request) =>
      documentPage(
        request.parent_hierarchy_node_id,
        request.parent_hierarchy_node_id === 1
      )
    );
  jest
    .mocked(updatePersona)
    .mockResolvedValue(
      new Response(JSON.stringify({ id: 1, name: agent.name }))
    );
  const view = render(
    <TooltipPrimitive.Provider>
      <AgentEditorPage agent={agent} />
    </TooltipPrimitive.Provider>
  );
  await act(async () => {
    fireEvent.change(screen.getByPlaceholderText("Name your agent"), {
      target: { value: "Updated agent" },
    });
  });
  const save = screen.getByRole("button", { name: "Save" });
  await waitFor(() => expect(save).toBeEnabled());
  await clickButton("knowledge-view-edit");
  await clickButton("knowledge-add-source-canvas");
  await clickButton("Open Course materials");
  await clickButton("Open Week 1");
  const file = await screen.findByRole("checkbox", {
    name: "Select document File in folder 2",
  });
  let resolvePage!: (page: HierarchyNodeDocumentsResponse) => void;
  jest.mocked(fetchHierarchyNodeDocuments).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        resolvePage = resolve;
      })
  );
  await act(async () => {
    fireEvent.click(file);
  });
  const form = screen.getByRole("button", { name: "Save" }).closest("form");
  if (!form) throw new Error("Missing agent form");
  return { ...view, form, resolvePage };
}

test("blocks saving a regular agent until its knowledge selection finishes", async () => {
  const { form, resolvePage } = await startPendingSelection();
  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  // Also exercise keyboard/programmatic submission, which bypasses the button.
  await act(async () => {
    fireEvent.submit(form);
  });
  expect(updatePersona).not.toHaveBeenCalled();
  await act(async () => {
    resolvePage(documentPage(1));
  });
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled()
  );
  await clickButton("Save");
  expect(updatePersona).toHaveBeenCalledWith(
    1,
    expect.objectContaining({
      hierarchy_node_ids: [3],
      document_ids: ["document-1"],
    })
  );
});

test("leaving a pending selection restores saving and ignores its late result", async () => {
  const { resolvePage } = await startPendingSelection();
  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  await clickButton("knowledge-sidebar-files");
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled()
  );
  await act(async () => {
    resolvePage(documentPage(1));
  });
  await clickButton("Save");
  expect(updatePersona).toHaveBeenCalledWith(
    1,
    expect.objectContaining({
      hierarchy_node_ids: [1],
      document_ids: [],
    })
  );
});
