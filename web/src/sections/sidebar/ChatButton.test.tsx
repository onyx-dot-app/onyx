import {
  fireEvent,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import { ChatSessionSharedStatus, type ChatSession } from "@/app/app/types";
import { useUnseenRuns } from "@/lib/chat/runStatus";
import ChatButton from "@/sections/sidebar/ChatButton";

const mockRename = jest.fn();
const mockRefresh = jest.fn();

jest.mock("@/app/app/services/lib", () => ({
  deleteChatSession: jest.fn(),
  renameChatSession: (...args: unknown[]) => mockRename(...args),
}));

jest.mock("@/hooks/useChatSessions", () => ({
  __esModule: true,
  default: () => ({
    refreshChatSessions: mockRefresh,
    removeSession: jest.fn(),
  }),
}));

jest.mock("@/lib/projects/providers", () => ({
  useProjectsContext: () => ({
    refreshCurrentProjectDetails: jest.fn(),
    projects: [],
    fetchProjects: jest.fn(),
    currentProjectId: null,
    createProject: jest.fn(),
  }),
}));

jest.mock("@/lib/navigation/hooks", () => ({
  useAppPosition: () => ({
    isChat: () => false,
    chat: () => null,
    linkToChat: () => ({ href: "/app?chatId=chat-1", onClick: jest.fn() }),
  }),
}));

jest.mock("@/lib/agents/hooks", () => ({
  usePinChatAgent: () => jest.fn(),
}));

jest.mock("@/lib/chat/hooks", () => ({
  ...jest.requireActual("@/lib/chat/hooks"),
  useChatExportMenu: () => ({
    exportMenuItem: {
      kind: "action",
      id: "export",
      title: "Export",
      onSelect: jest.fn(),
    },
  }),
}));

jest.mock("@/sections/modals/ShareChatSessionModal", () => ({
  __esModule: true,
  default: () => null,
}));

jest.mock("@/lib/agents/components", () => ({
  MoveCustomAgentChatModal: () => null,
}));

const chatSession: ChatSession = {
  id: "chat-1",
  name: "Quarterly plan",
  persona_id: 0,
  time_created: new Date(Date.now() - 2 * 3_600_000 - 5 * 60_000).toISOString(),
  time_updated: new Date(Date.now() - 2 * 3_600_000 - 5 * 60_000).toISOString(),
  shared_status: ChatSessionSharedStatus.Private,
  project_id: null,
  current_alternate_model: "",
  current_temperature_override: null,
  current_reasoning_effort_override: null,
};

beforeEach(() => {
  jest.clearAllMocks();
  mockRename.mockResolvedValue({ ok: true });
  mockRefresh.mockResolvedValue(undefined);
  useUnseenRuns.getState().clearAll();
});

function openContextMenu() {
  render(<ChatButton chatSession={chatSession} />);
  fireEvent.contextMenu(screen.getByTestId("ChatButton"), {
    clientX: 40,
    clientY: 60,
  });
}

test("the row shows the relative time of its last update", () => {
  render(<ChatButton chatSession={chatSession} />);
  expect(screen.getByText("2h")).toBeInTheDocument();
});

test("right-click opens the row menu", async () => {
  openContextMenu();
  expect(
    await screen.findByRole("menuitem", { name: "Rename" })
  ).toBeInTheDocument();
  expect(
    screen.getByRole("menuitem", { name: "Regenerate title" })
  ).toBeInTheDocument();
});

test("Mark as unread marks the session, then reads Mark as read", async () => {
  openContextMenu();
  fireEvent.click(
    await screen.findByRole("menuitem", { name: "Mark as unread" })
  );
  expect(useUnseenRuns.getState().unseen.get("chat-1")).toBe("done");

  fireEvent.contextMenu(screen.getByTestId("ChatButton"));
  fireEvent.click(
    await screen.findByRole("menuitem", { name: "Mark as read" })
  );
  expect(useUnseenRuns.getState().unseen.has("chat-1")).toBe(false);
});

test("Regenerate title asks the server for a new name", async () => {
  openContextMenu();
  fireEvent.click(
    await screen.findByRole("menuitem", { name: "Regenerate title" })
  );
  await waitFor(() =>
    expect(mockRename).toHaveBeenCalledWith("chat-1", null, true)
  );
  await waitFor(() => expect(mockRefresh).toHaveBeenCalled());
});

test("double-click on the row starts the rename", () => {
  render(<ChatButton chatSession={chatSession} />);
  fireEvent.doubleClick(screen.getByTestId("ChatButton"));
  expect(screen.getByRole("textbox")).toBeInTheDocument();
});

test("the menu opened from the row takes focus on its trigger", async () => {
  openContextMenu();
  await screen.findByRole("menuitem", { name: "Rename" });
  expect(screen.getByRole("button", { name: "Chat options" })).toHaveFocus();
});

test("right-click after a hover closes the tooltip and focuses the options button", async () => {
  render(<ChatButton chatSession={chatSession} />);
  const user = setupUser();
  await user.hover(screen.getByRole("link", { name: "Quarterly plan" }));
  expect(await screen.findByRole("tooltip")).toBeInTheDocument();

  fireEvent.contextMenu(screen.getByTestId("ChatButton"), {
    clientX: 40,
    clientY: 60,
  });
  await screen.findByRole("menuitem", { name: "Rename" });
  await waitFor(() =>
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument()
  );
  expect(screen.getByRole("button", { name: "Chat options" })).toHaveFocus();
});
