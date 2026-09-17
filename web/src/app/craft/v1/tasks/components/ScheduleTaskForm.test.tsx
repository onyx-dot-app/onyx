import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import ScheduleTaskForm, {
  defaultFormInitial,
  type ScheduleTaskFormInitial,
} from "@/app/craft/v1/tasks/components/ScheduleTaskForm";
import type { PickerEntry } from "@/lib/skills/picker";

const mockRouterPush = jest.fn();
const mockCreateScheduledTask = jest.fn();
const mockUpdateScheduledTask = jest.fn();
const mockMutate = jest.fn();

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockRouterPush }),
}));

jest.mock("swr", () => ({
  ...jest.requireActual("swr"),
  useSWRConfig: () => ({ mutate: mockMutate }),
}));

jest.mock("@/hooks/useUserSkills", () => ({
  __esModule: true,
  default: () => ({ data: { builtins: [], customs: [] } }),
}));

jest.mock("@/hooks/useUserExternalApps", () => ({
  __esModule: true,
  default: () => ({ data: [] }),
}));

jest.mock("@/lib/tools/hooks", () => ({
  useCraftMcpServers: () => ({ data: { mcp_servers: [] } }),
}));

jest.mock("@/app/craft/v1/tasks/api", () => ({
  createScheduledTask: (...args: unknown[]) => mockCreateScheduledTask(...args),
  updateScheduledTask: (...args: unknown[]) => mockUpdateScheduledTask(...args),
}));

jest.mock("@/app/craft/v1/tasks/components/ScheduleEditor", () => ({
  __esModule: true,
  default: () => null,
}));

jest.mock("@/app/craft/v1/tasks/components/PreApprovalPicker", () => ({
  __esModule: true,
  default: ({
    onAppChange,
    onMcpServerChange,
  }: {
    onAppChange: (ids: number[]) => void;
    onMcpServerChange: (ids: number[]) => void;
  }) => (
    <div>
      <button type="button" onClick={() => onAppChange([11])}>
        Pre-approve app
      </button>
      <button type="button" onClick={() => onMcpServerChange([22])}>
        Pre-approve MCP server
      </button>
    </div>
  ),
}));

jest.mock("@/sections/input/EntryPickerPopover", () => ({
  __esModule: true,
  default: ({
    open,
    onSelect,
  }: {
    open: boolean;
    onSelect: (entry: PickerEntry) => void;
  }) =>
    open ? (
      <div>
        <button
          type="button"
          onClick={() =>
            onSelect({
              kind: "app",
              externalAppId: 1,
              name: "Slack",
              appType: "SLACK",
              authenticated: true,
            })
          }
        >
          Select connected Slack
        </button>
        <button
          type="button"
          onClick={() =>
            onSelect({
              kind: "app",
              externalAppId: 2,
              name: "Gmail",
              appType: "GMAIL",
              authenticated: false,
            })
          }
        >
          Connect Gmail
        </button>
      </div>
    ) : null,
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
    mockRouterPush.mockReset();
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
    await user.click(
      screen.getByRole("button", { name: "Select connected Slack" })
    );

    await waitFor(() =>
      expect(prompt).toHaveValue('[Use external app "Slack" (ID: 1)] ')
    );
    expect(mockRouterPush).not.toHaveBeenCalled();
  });

  it("routes an unauthenticated app to connection without inserting it", async () => {
    const user = setupUser();
    renderForm();

    const prompt = screen.getByTestId("task-prompt-input");
    await user.type(prompt, "/");
    await user.click(screen.getByRole("button", { name: "Connect Gmail" }));

    expect(mockRouterPush).toHaveBeenCalledWith("/craft/v1/apps?connect=2");
    expect(prompt).toHaveValue("/");
  });

  it("saves app and MCP server pre-approvals independently", async () => {
    const user = setupUser();
    renderForm();

    await user.type(screen.getByTestId("task-name-input"), "Daily report");
    await user.type(screen.getByTestId("task-prompt-input"), "Make a report");
    await user.click(screen.getByRole("button", { name: "Pre-approve app" }));
    await user.click(
      screen.getByRole("button", { name: "Pre-approve MCP server" })
    );
    await user.click(screen.getByRole("button", { name: /^Save$/ }));

    await waitFor(() =>
      expect(mockCreateScheduledTask).toHaveBeenCalledWith(
        expect.objectContaining({
          pre_approved_app_ids: [11],
          pre_approved_mcp_server_ids: [22],
        })
      )
    );
    expect(mockMutate).toHaveBeenCalledWith("/api/build/scheduled-tasks");
  });

  it("preserves both grant kinds when an existing task is edited", async () => {
    const user = setupUser();
    renderForm({
      isEdit: true,
      initial: {
        ...defaultFormInitial(),
        taskId: "task-id",
        name: "Daily report",
        prompt: "Make a report",
        preApprovedAppIds: [11],
        preApprovedMcpServerIds: [22],
      },
    });

    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() =>
      expect(mockUpdateScheduledTask).toHaveBeenCalledWith(
        "task-id",
        expect.objectContaining({
          pre_approved_app_ids: [11],
          pre_approved_mcp_server_ids: [22],
        })
      )
    );
    expect(mockMutate).toHaveBeenCalledWith(
      "/api/build/scheduled-tasks/task-id",
      { id: "task-id" },
      { revalidate: false }
    );
    expect(mockRouterPush).toHaveBeenCalledWith("/craft/v1/tasks/task-id");
  });
});
