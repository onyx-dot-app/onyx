import { render, screen } from "@tests/setup/test-utils";
import ProjectContextPanel from "@/lib/projects/components/ProjectContextPanel";
import { UserFileStatus, type ProjectFile } from "@/lib/projects/types";
import { ChatFileType } from "@/app/app/types";

const projectFile: ProjectFile = {
  id: "file-1",
  name: "notes.txt",
  project_id: 1,
  user_id: null,
  file_id: "stored-1",
  created_at: "2026-01-01T00:00:00Z",
  status: UserFileStatus.COMPLETED,
  file_type: "text/plain",
  last_accessed_at: "2026-01-01T00:00:00Z",
  chat_file_type: ChatFileType.PLAIN_TEXT,
  token_count: 1500,
  chunk_count: 1,
};

// One object, so the context's arrays keep their identity across renders.
const mockProjectsContext = {
  currentProjectDetails: { project: { instructions: "" } },
  currentProjectId: 1,
  unlinkFileFromProject: jest.fn(),
  linkFileToProject: jest.fn(),
  allCurrentProjectFiles: [projectFile],
  allRecentFiles: [],
  isLoadingProjectDetails: false,
  beginUpload: jest.fn(),
  projects: [{ id: 1, name: "Project" }],
  renameProject: jest.fn(),
};
jest.mock("@/lib/projects/providers", () => ({
  useProjectsContext: () => mockProjectsContext,
}));

const originalFetch = global.fetch;
afterEach(() => {
  global.fetch = originalFetch;
});

test("the panel warns when the project's files exceed its agent's budget", async () => {
  global.fetch = jest.fn(
    async () =>
      new Response(JSON.stringify({ max_tokens: 1000 }), { status: 200 })
  );

  render(
    <ProjectContextPanel
      projectTokenCount={1500}
      agentId={7}
      hasAnyProvider={true}
    />
  );

  expect(
    await screen.findByText(/This project exceeds the model's context limits/)
  ).toBeInTheDocument();
  expect(jest.mocked(global.fetch).mock.calls.map(([input]) => input)).toEqual([
    "/api/chat/max-selected-document-tokens?persona_id=7",
  ]);
});

test("without an LLM provider the panel requests no budget and uses the default", async () => {
  global.fetch = jest.fn(
    async () =>
      new Response(JSON.stringify({ max_tokens: 1000 }), { status: 200 })
  );

  render(
    <ProjectContextPanel
      projectTokenCount={1500}
      agentId={7}
      hasAnyProvider={false}
    />
  );

  // Under the default budget, the files fit and no warning shows.
  expect(await screen.findByText("notes.txt")).toBeInTheDocument();
  expect(
    screen.queryByText(/This project exceeds the model's context limits/)
  ).not.toBeInTheDocument();
  expect(global.fetch).not.toHaveBeenCalled();
});
