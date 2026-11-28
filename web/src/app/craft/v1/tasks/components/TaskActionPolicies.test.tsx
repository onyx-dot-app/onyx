import { useState, type ReactElement } from "react";
import { render, screen, setupUser } from "@tests/setup/test-utils";
import TaskActionPolicies from "@/app/craft/v1/tasks/components/TaskActionPolicies";
import type {
  TaskIntegrationLink,
  TaskIntegrationView,
} from "@/app/craft/v1/tasks/types";

jest.mock("next/navigation", () => ({
  ...jest.requireActual<typeof import("@tests/setup/mocks/nextNavigation")>(
    "@tests/setup/mocks/nextNavigation"
  ).nextNavigationMock,
  useRouter: () => ({ push: jest.fn() }),
  usePathname: () => "/craft/v1/tasks",
}));

const LINEAR_MCP: TaskIntegrationView = {
  id: 7,
  name: "Linear",
  kind: "mcp",
  app_type: null,
  status: { state: "connected", reason: null },
  actions: [
    {
      key: "search",
      display_name: "Search issues",
      description: "Find issues",
      integration_policy: "allow",
      locked: false,
    },
    {
      key: "create",
      display_name: "Create issue",
      description: null,
      integration_policy: "ask",
      locked: false,
    },
  ],
  enabled: false,
  action_settings: null,
  runnable: true,
};

function integrationView(
  overrides: Partial<TaskIntegrationView> = {}
): TaskIntegrationView {
  return { ...LINEAR_MCP, ...overrides };
}

let mockData: TaskIntegrationView[] = [integrationView()];
const mockSave = jest.fn();
let fetchSpy: jest.SpyInstance;

function Form({ taskId = null }: { taskId?: string | null }) {
  const [value, setValue] = useState<TaskIntegrationLink[] | null>(null);
  return (
    <>
      <TaskActionPolicies taskId={taskId} value={value} onChange={setValue} />
      <button disabled={value === null} onClick={() => mockSave(value)}>
        Save task
      </button>
    </>
  );
}

async function renderLoaded(ui: ReactElement) {
  render(ui);
  await screen.findByRole("switch", { name: "Enable Linear for this task" });
}

beforeEach(() => {
  mockData = [integrationView()];
  mockSave.mockClear();
  fetchSpy = jest
    .spyOn(global, "fetch")
    .mockImplementation(async () => new Response(JSON.stringify(mockData)));
});

afterEach(() => {
  jest.restoreAllMocks();
});

it("starts a new task with no integrations and turns one on with inherited actions", async () => {
  const user = setupUser();
  await renderLoaded(<Form />);
  expect(screen.getByText("Disabled for this task")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Save task" }));
  expect(mockSave).toHaveBeenLastCalledWith([]);

  await user.click(
    screen.getByRole("switch", { name: "Enable Linear for this task" })
  );
  expect(screen.getByText("1 allow · 1 ask · 0 blocked")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Save task" }));
  expect(mockSave).toHaveBeenLastCalledWith([
    {
      integration_id: 7,
      action_settings: { default: "inherit", actions: {} },
    },
  ]);

  await user.click(
    screen.getByRole("switch", { name: "Enable Linear for this task" })
  );
  await user.click(screen.getByRole("button", { name: "Save task" }));
  expect(mockSave).toHaveBeenLastCalledWith([]);
});

it("keeps the stored settings of an existing task", async () => {
  const user = setupUser();
  mockData = [
    integrationView({
      enabled: true,
      action_settings: { default: "ask", actions: { search: "allow" } },
    }),
  ];
  await renderLoaded(<Form taskId="task-1" />);
  expect(fetchSpy).toHaveBeenCalledWith(
    "/api/build/scheduled-tasks/task-1/action-policies"
  );
  expect(screen.getByText("1 allow · 1 ask · 0 blocked")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Save task" }));
  expect(mockSave).toHaveBeenLastCalledWith([
    {
      integration_id: 7,
      action_settings: { default: "ask", actions: { search: "allow" } },
    },
  ]);
});

it("turning an integration off and on again keeps its action settings", async () => {
  const user = setupUser();
  mockData = [
    integrationView({
      enabled: true,
      action_settings: { default: "ask", actions: { search: "allow" } },
    }),
  ];
  await renderLoaded(<Form taskId="task-1" />);
  const toggle = screen.getByRole("switch", {
    name: "Enable Linear for this task",
  });
  await user.click(toggle);
  await user.click(toggle);
  await user.click(screen.getByRole("button", { name: "Save task" }));
  expect(mockSave).toHaveBeenLastCalledWith([
    {
      integration_id: 7,
      action_settings: { default: "ask", actions: { search: "allow" } },
    },
  ]);
});

it("editing an integration that was turned off keeps its other settings", async () => {
  const user = setupUser();
  mockData = [
    integrationView({
      enabled: true,
      action_settings: { default: "ask", actions: { search: "blocked" } },
    }),
  ];
  await renderLoaded(<Form taskId="task-1" />);
  await user.click(
    screen.getByRole("switch", { name: "Enable Linear for this task" })
  );
  await user.click(screen.getByRole("button", { name: "Manage actions" }));
  await user.click(
    screen.getByRole("combobox", { name: "Setting for Create issue" })
  );
  await user.keyboard("{ArrowDown}{ArrowDown}{ArrowDown}{ArrowDown}{Enter}");
  await user.click(screen.getByRole("button", { name: "Save changes" }));
  await user.click(screen.getByRole("button", { name: "Save task" }));
  expect(mockSave).toHaveBeenLastCalledWith([
    {
      integration_id: 7,
      action_settings: {
        default: "ask",
        actions: { search: "blocked", create: "blocked" },
      },
    },
  ]);
});

it("does not offer Allow for a locked action", async () => {
  const user = setupUser();
  mockData = [
    integrationView({
      actions: LINEAR_MCP.actions.map((action) => ({
        ...action,
        locked: action.key === "create",
      })),
    }),
  ];
  await renderLoaded(<Form />);
  await user.click(screen.getByRole("button", { name: "Manage actions" }));
  await user.click(
    screen.getByRole("combobox", { name: "Setting for Create issue" })
  );
  expect(screen.getByRole("option", { name: "Allow" })).toHaveAttribute(
    "aria-disabled",
    "true"
  );
});

it("counts a locked task Allow with the integration policy", async () => {
  mockData = [
    integrationView({
      enabled: true,
      action_settings: { default: "allow", actions: {} },
      actions: LINEAR_MCP.actions.map((action) => ({
        ...action,
        locked: action.key === "create",
      })),
    }),
  ];
  await renderLoaded(<Form taskId="task-1" />);
  expect(screen.getByText("1 allow · 1 ask · 0 blocked")).toBeInTheDocument();
});

it("sets an action to Allow, Ask, Blocked or the integration setting", async () => {
  const user = setupUser();
  await renderLoaded(<Form />);
  await user.click(screen.getByRole("button", { name: "Manage actions" }));
  await user.click(
    screen.getByRole("combobox", { name: "Setting for Create issue" })
  );
  for (const label of [
    "Use integration setting (Ask)",
    "Allow",
    "Ask",
    "Blocked",
  ])
    expect(screen.getByRole("option", { name: label })).toBeInTheDocument();
  await user.keyboard("{ArrowDown}{ArrowDown}{ArrowDown}{ArrowDown}{Enter}");
  await user.click(screen.getByRole("button", { name: "Save changes" }));

  expect(screen.getByText("1 allow · 0 ask · 1 blocked")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Save task" }));
  expect(mockSave).toHaveBeenLastCalledWith([
    {
      integration_id: 7,
      action_settings: { default: "inherit", actions: { create: "blocked" } },
    },
  ]);
});

it("shows the sign-in reason of an integration that is not connected", async () => {
  mockData = [
    integrationView({
      status: {
        state: "not_connected",
        reason: "Connect your Linear account to use it.",
      },
    }),
  ];
  await renderLoaded(<Form />);
  expect(
    screen.getByText("Connect your Linear account to use it.")
  ).toBeInTheDocument();
});

it("reports a load failure without enabling the parent save", async () => {
  fetchSpy.mockImplementation(
    async () =>
      new Response(JSON.stringify({ detail: "offline" }), { status: 500 })
  );
  render(<Form />);
  expect(
    await screen.findByText("Could not load approval settings.")
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Save task" })).toBeDisabled();
});

it("warns when Craft cannot run a linked integration", async () => {
  mockData = [integrationView({ enabled: true, runnable: false })];
  await renderLoaded(<Form taskId="task-1" />);
  expect(
    screen.getByText("Craft cannot run Linear now, so the task skips it.")
  ).toBeVisible();
});
