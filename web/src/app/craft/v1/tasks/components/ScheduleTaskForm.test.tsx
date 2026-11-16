import {
  fireEvent,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import ScheduleTaskForm, {
  defaultFormInitial,
  type ScheduleTaskFormInitial,
} from "@/app/craft/v1/tasks/components/ScheduleTaskForm";

const mockRouterReplace = jest.fn();
const mockCreateScheduledTask = jest.fn();
const mockUpdateScheduledTask = jest.fn();
const mockMutate = jest.fn();

jest.mock("next/navigation", () => ({
  ...jest.requireActual<typeof import("@tests/setup/mocks/nextNavigation")>(
    "@tests/setup/mocks/nextNavigation"
  ).nextNavigationMock,
  useRouter: () => ({ replace: mockRouterReplace }),
}));

beforeEach(() => {
  // Navigation skips a URL it is already on, so each test starts here.
  window.history.replaceState(null, "", "/craft/v1/tasks/new");
});

jest.mock("swr", () => ({
  ...jest.requireActual("swr"),
  useSWRConfig: () => ({ mutate: mockMutate }),
}));

const mockSkills = {
  builtins: [
    {
      name: "pptx",
      description: "Make slides",
      is_available: true,
      enabled: true,
    },
  ],
  customs: [],
};
jest.mock("@/hooks/useUserSkills", () => ({
  __esModule: true,
  default: () => ({ data: mockSkills }),
}));

const mockExternalApps = [
  { id: 1, name: "Slack", app_type: "SLACK", authenticated: true },
  { id: 2, name: "Gmail", app_type: "GMAIL", authenticated: false },
];
jest.mock("@/hooks/useUserExternalApps", () => ({
  __esModule: true,
  default: () => ({ data: mockExternalApps }),
}));

const mockCraftMcp = { data: { mcp_servers: [] } };
jest.mock("@/lib/mcp/hooks", () => ({
  useCraftMcpServers: () => mockCraftMcp,
}));

jest.mock("@/app/craft/v1/tasks/api", () => ({
  createScheduledTask: (...args: unknown[]) => mockCreateScheduledTask(...args),
  updateScheduledTask: (...args: unknown[]) => mockUpdateScheduledTask(...args),
}));

jest.mock("@/app/craft/v1/tasks/components/ScheduleEditor", () => ({
  __esModule: true,
  default: () => null,
}));

jest.mock("@/app/craft/v1/tasks/components/TaskActionPolicies", () => ({
  __esModule: true,
  default: function MockPermissions({
    onChange,
  }: {
    onChange: (value: unknown) => void;
  }) {
    const { useEffect } = jest.requireActual("react");
    useEffect(() => {
      onChange([
        {
          gated_app_id: 11,
          enabled: true,
          action_policies: { send: "ALWAYS" },
        },
        {
          gated_app_id: 22,
          enabled: false,
          action_policies: { read: "ASK" },
        },
      ]);
    }, [onChange]);
    return null;
  },
}));

function renderForm({
  initial = defaultFormInitial(),
  isEdit = false,
}: {
  initial?: ScheduleTaskFormInitial;
  isEdit?: boolean;
} = {}) {
  render(
    <ScheduleTaskForm
      initial={initial}
      isEdit={isEdit}
      title={isEdit ? "Edit scheduled task" : "Create scheduled task"}
      onBack={jest.fn()}
    />
  );
}

describe("ScheduleTaskForm app picker", () => {
  beforeEach(() => {
    mockRouterReplace.mockReset();
    mockCreateScheduledTask.mockReset();
    mockUpdateScheduledTask.mockReset();
    mockMutate.mockReset();
    mockCreateScheduledTask.mockResolvedValue({ id: "task-id" });
    mockUpdateScheduledTask.mockResolvedValue({ id: "task-id" });
    mockMutate.mockResolvedValue(undefined);
  });

  it("inserts an authenticated app into the task prompt", async () => {
    const user = setupUser();
    renderForm();

    const prompt = screen.getByTestId("task-prompt-input");
    await user.type(prompt, "/");
    await user.click(screen.getByTestId("app-picker-row-1"));

    await waitFor(() =>
      expect(prompt).toHaveValue('[Use external app "Slack" (ID: 1)] ')
    );
    expect(mockRouterReplace).not.toHaveBeenCalled();
  });

  it("routes an unauthenticated app to connection without inserting it", async () => {
    const user = setupUser();
    renderForm();

    const prompt = screen.getByTestId("task-prompt-input");
    await user.type(prompt, "/");
    await user.click(screen.getByTestId("app-picker-row-2"));

    expect(mockRouterReplace).toHaveBeenCalledWith("/craft/v1/apps?connect=2");
    expect(prompt).toHaveValue("/");
  });

  it("opens only on input, and a caret move closes it", async () => {
    const user = setupUser();
    renderForm();
    const prompt = screen.getByTestId("task-prompt-input");
    await user.type(prompt, "/pptx now");
    expect(screen.queryByTestId("skill-picker-popover")).toBeNull();

    // The caret lands inside `/pp|tx`, which matches, but a move never opens.
    await user.keyboard("{Home}{ArrowRight}{ArrowRight}{ArrowRight}");
    fireEvent(prompt, new Event("selectionchange", { bubbles: true }));
    expect(screen.queryByTestId("skill-picker-popover")).toBeNull();

    await user.keyboard("{Backspace}");
    expect(await screen.findByTestId("skill-picker-popover")).toBeVisible();
    await user.keyboard("{ArrowLeft}");
    // Browsers fire `selectionchange` on a textarea's caret move; jsdom does not.
    fireEvent(prompt, new Event("selectionchange", { bubbles: true }));
    expect(screen.queryByTestId("skill-picker-popover")).toBeNull();
  });

  it("a paste never opens it and closes an open one", async () => {
    const user = setupUser();
    renderForm();
    const prompt = screen.getByTestId("task-prompt-input");
    await user.click(prompt);
    await user.paste("/pptx");
    expect(screen.queryByTestId("skill-picker-popover")).toBeNull();
    await user.keyboard("{Enter}");
    expect(prompt).toHaveValue("/pptx\n");

    await user.type(prompt, "/p");
    expect(await screen.findByTestId("skill-picker-popover")).toBeVisible();
    await user.paste("ptx");
    expect(screen.queryByTestId("skill-picker-popover")).toBeNull();
  });

  it("closes on a word that matches nothing, with substring matching", async () => {
    const user = setupUser();
    renderForm();
    const prompt = screen.getByTestId("task-prompt-input");
    await user.type(prompt, "/ptx");
    expect(await screen.findByTestId("skill-picker-row-pptx")).toBeVisible();
    await user.type(prompt, "z");
    expect(screen.queryByTestId("skill-picker-popover")).toBeNull();
  });

  it("Esc hides it until its slash is deleted", async () => {
    const user = setupUser();
    renderForm();
    const prompt = screen.getByTestId("task-prompt-input");
    await user.type(prompt, "/p");
    await screen.findByTestId("skill-picker-popover");

    await user.keyboard("{Escape}p");
    expect(screen.queryByTestId("skill-picker-popover")).toBeNull();
    await user.paste("t");
    await user.keyboard("x");
    expect(screen.queryByTestId("skill-picker-popover")).toBeNull();
    await user.keyboard("{Backspace}{Backspace}");
    await user.keyboard("{Backspace}{Backspace}{Backspace}/p");
    expect(await screen.findByTestId("skill-picker-popover")).toBeVisible();
  });

  it("a pick replaces the whole word around the caret", async () => {
    const user = setupUser();
    renderForm();
    const prompt = screen.getByTestId("task-prompt-input");
    await user.type(prompt, "make /ptx now");
    await user.keyboard(
      "{ArrowLeft}{ArrowLeft}{ArrowLeft}{ArrowLeft}{ArrowLeft}{ArrowLeft}{ArrowLeft}"
    );
    await user.keyboard("p");
    await user.keyboard("{Enter}");
    await waitFor(() => expect(prompt).toHaveValue("make /pptx  now"));
  });

  it("saves independent action choices for apps and MCP servers", async () => {
    const user = setupUser();
    renderForm();

    await user.type(screen.getByTestId("task-name-input"), "Daily report");
    await user.type(screen.getByTestId("task-prompt-input"), "Make a report");
    await user.click(screen.getByRole("button", { name: /^Save$/ }));

    await waitFor(() =>
      expect(mockCreateScheduledTask).toHaveBeenCalledWith(
        expect.objectContaining({
          action_policies: [
            {
              gated_app_id: 11,
              enabled: true,
              action_policies: { send: "ALWAYS" },
            },
            {
              gated_app_id: 22,
              enabled: false,
              action_policies: { read: "ASK" },
            },
          ],
        })
      )
    );
    expect(mockMutate).toHaveBeenCalledWith("/api/build/scheduled-tasks");
  });

  it("saves the displayed action choices when an existing task is edited", async () => {
    const user = setupUser();
    renderForm({
      isEdit: true,
      initial: {
        ...defaultFormInitial(),
        taskId: "task-id",
        name: "Daily report",
        prompt: "Make a report",
      },
    });

    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() =>
      expect(mockUpdateScheduledTask).toHaveBeenCalledWith(
        "task-id",
        expect.objectContaining({
          action_policies: [
            {
              gated_app_id: 11,
              enabled: true,
              action_policies: { send: "ALWAYS" },
            },
            {
              gated_app_id: 22,
              enabled: false,
              action_policies: { read: "ASK" },
            },
          ],
        })
      )
    );
    expect(mockMutate).toHaveBeenCalledWith(
      "/api/build/scheduled-tasks/task-id",
      { id: "task-id" },
      { revalidate: false }
    );
    expect(mockMutate).toHaveBeenCalledWith(
      "/api/build/scheduled-tasks/task-id/action-policies"
    );
    expect(mockRouterReplace).toHaveBeenCalledWith("/craft/v1/tasks/task-id");
  });
});
