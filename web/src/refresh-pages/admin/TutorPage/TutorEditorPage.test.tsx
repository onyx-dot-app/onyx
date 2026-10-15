import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import TutorEditorPage from "@/refresh-pages/admin/TutorPage/TutorEditorPage";
import type {
  FullPersona,
  HierarchyNodeSnapshot,
} from "@/app/admin/agents/interfaces";
import type { PersonaUpsertParameters } from "@/app/admin/agents/lib";
import { ValidSources } from "@/lib/types";
import {
  fetchHierarchyNodes,
  fetchHierarchyNodeDocuments,
} from "@/lib/hierarchy/svc";
import { toast } from "@/hooks/useToast";

jest.mock("@/lib/hierarchy/svc");
jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn() }),
  useSearchParams: () =>
    new URLSearchParams(
      "lti_context_id=course-123&lti_canvas_course_node_id=1"
    ),
}));
jest.mock("swr", () => ({
  __esModule: true,
  default: () => ({ data: { canvas_course_node_id: 1 } }),
}));
jest.mock("@/hooks/useAgents", () => ({
  useAgents: () => ({ refresh: jest.fn() }),
}));
jest.mock("@/hooks/useAvailableTools", () => ({
  useAvailableTools: () => ({
    tools: [{ id: 9, in_code_tool_id: "SearchTool" }],
    isLoading: false,
  }),
}));
jest.mock("@/hooks/useLLMProviders", () => ({
  useLLMProviders: () => ({ llmProviders: [] }),
}));
jest.mock("@/providers/SettingsProvider", () => ({
  useVectorDbEnabled: () => true,
}));
jest.mock("@/lib/hooks", () => ({
  useLabels: () => ({
    labels: [{ id: 7, name: "Virtual Tutor" }],
    createLabel: jest.fn(),
  }),
}));
jest.mock("@/hooks/useToast", () => ({
  toast: { success: jest.fn(), error: jest.fn() },
}));
jest.mock("@/refresh-pages/admin/AgentsPage/svc", () => ({
  deleteAgent: jest.fn(),
}));

const courseFolder: HierarchyNodeSnapshot = {
  id: 1,
  raw_node_id: "course-123",
  display_name: "Course materials",
  link: null,
  source: ValidSources.Canvas,
  node_type: "folder",
};
const readingsFolder: HierarchyNodeSnapshot = {
  ...courseFolder,
  id: 2,
  raw_node_id: "readings",
  display_name: "Readings",
};
const tutor: FullPersona = {
  id: 77,
  name: "Course tutor",
  description: "",
  tools: [],
  starter_messages: [],
  document_sets: [],
  is_public: true,
  is_listed: true,
  display_priority: null,
  is_featured: false,
  builtin_persona: false,
  owner: null,
  user_file_ids: [],
  users: [],
  groups: [],
  system_prompt: "",
  replace_base_system_prompt: true,
  task_prompt: "",
  datetime_aware: false,
  search_start_date: null,
  labels: [
    { id: 7, name: "Virtual Tutor" },
    { id: 8, name: "course-123" },
  ],
  hierarchy_nodes: [courseFolder],
  attached_documents: [],
};

function renderEditor(existingTutor?: FullPersona) {
  return render(
    <TooltipPrimitive.Provider>
      <TutorEditorPage tutor={existingTutor} />
    </TooltipPrimitive.Provider>
  );
}

beforeEach(() => {
  jest.mocked(fetchHierarchyNodes).mockResolvedValue({
    nodes: [
      { id: 1, title: "Course materials", parent_id: null, link: null },
      { id: 2, title: "Readings", parent_id: 1, link: null },
    ],
  });
  jest
    .mocked(fetchHierarchyNodeDocuments)
    .mockImplementation(async (request) => ({
      documents: [
        {
          id: `document-${request.parent_hierarchy_node_id}`,
          title: `File in folder ${request.parent_hierarchy_node_id}`,
          parent_id: request.parent_hierarchy_node_id,
          link: null,
          last_modified: null,
          last_synced: null,
        },
      ],
      next_cursor: null,
      page_size: 100,
      sort_field: "name",
      sort_direction: "asc",
      folder_position: "on_top",
    }));
  jest
    .spyOn(global, "fetch")
    .mockResolvedValue(
      new Response(JSON.stringify({ name: tutor.name }), { status: 200 })
    );
});

afterEach(() => {
  jest.restoreAllMocks();
});

test.each([false, true])(
  "saving and reopening preserves Canvas deselections (clear all: %s)",
  async (clearAll) => {
    const view = renderEditor(tutor);
    const file = await screen.findByRole("checkbox", {
      name: "Select document File in folder 1",
    });
    expect(file).toHaveAttribute("aria-checked", "true");

    await act(async () => {
      fireEvent.click(
        clearAll
          ? screen.getByRole("checkbox", { name: "Select all items" })
          : file
      );
    });
    expect(file).toHaveAttribute("aria-checked", "false");

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Save" }));
    });
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(
        'Tutor "Course tutor" updated successfully'
      )
    );

    const call = jest
      .mocked(global.fetch)
      .mock.calls.find(([url]) => url === "/api/persona/77");
    if (!call || typeof call[1]?.body !== "string") {
      throw new Error("Missing tutor PATCH request");
    }
    const saved: PersonaUpsertParameters = JSON.parse(call[1].body);
    expect(call[1].method).toBe("PATCH");
    expect(saved.document_ids).toEqual([]);
    expect(saved.hierarchy_node_ids).toEqual(clearAll ? [] : [2]);
    expect(saved.tool_ids).toEqual(clearAll ? [] : [9]);
    expect(saved.lti_context_id).toBe("course-123");

    view.unmount();
    renderEditor({
      ...tutor,
      hierarchy_nodes: [courseFolder, readingsFolder].filter(
        (folder) => saved.hierarchy_node_ids?.includes(folder.id)
      ),
    });
    expect(
      await screen.findByRole("checkbox", {
        name: "Select document File in folder 1",
      })
    ).toHaveAttribute("aria-checked", "false");
    expect(
      screen.getByRole("checkbox", { name: "Select folder Readings" })
    ).toHaveAttribute("aria-checked", clearAll ? "false" : "true");
  }
);

test("new tutors default to the Canvas course", async () => {
  renderEditor();
  expect(
    await screen.findByRole("checkbox", {
      name: "Select document File in folder 1",
    })
  ).toHaveAttribute("aria-checked", "true");
});

test("a tutor with only an individual document keeps the course unselected", async () => {
  renderEditor({
    ...tutor,
    hierarchy_nodes: [],
    attached_documents: [
      {
        id: "document-1",
        title: "File in folder 1",
        parent_id: 1,
        link: null,
        last_modified: null,
        last_synced: null,
        source: ValidSources.Canvas,
      },
    ],
  });
  expect(
    await screen.findByRole("checkbox", {
      name: "Select document File in folder 1",
    })
  ).toHaveAttribute("aria-checked", "true");
  expect(
    screen.getByRole("checkbox", { name: "Select folder Readings" })
  ).toHaveAttribute("aria-checked", "false");
});
