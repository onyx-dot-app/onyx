import { useState } from "react";
import { render, screen, setupUser } from "@tests/setup/test-utils";
import TaskActionPolicies from "@/app/craft/v1/tasks/components/TaskActionPolicies";
import type {
  TaskIntegrationView,
  TaskPluginLink,
  TaskPluginView,
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
  name: "Linear MCP",
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
};

function pluginView(overrides: Partial<TaskPluginView> = {}): TaskPluginView {
  return {
    plugin_id: "plugin-1",
    plugin_name: "Linear",
    enabled: false,
    action_settings: null,
    integrations: [LINEAR_MCP],
    ...overrides,
  };
}

let mockData: TaskPluginView[] = [pluginView()];
let mockError: Error | undefined;
const mockSave = jest.fn();
jest.mock("swr", () => ({
  ...jest.requireActual("swr"),
  __esModule: true,
  default: (
    _key: string,
    _fetcher: unknown,
    options?: { onSuccess?: (data: TaskPluginView[]) => void }
  ) => {
    const React = jest.requireActual<typeof import("react")>("react");
    React.useEffect(() => {
      if (!mockError) options?.onSuccess?.(mockData);
    }, []);
    return {
      data: mockError ? undefined : mockData,
      error: mockError,
      isValidating: false,
      mutate: jest.fn(),
    };
  },
}));

function Form({ taskId = null }: { taskId?: string | null }) {
  const [value, setValue] = useState<TaskPluginLink[] | null>(null);
  return (
    <>
      <TaskActionPolicies taskId={taskId} value={value} onChange={setValue} />
      <button disabled={value === null} onClick={() => mockSave(value)}>
        Save task
      </button>
    </>
  );
}

beforeEach(() => {
  mockData = [pluginView()];
  mockError = undefined;
  mockSave.mockClear();
});

it("starts a new task with no plugins and turns a plugin on with inherited actions", async () => {
  const user = setupUser();
  render(<Form />);
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
      plugin_id: "plugin-1",
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
    pluginView({
      enabled: true,
      action_settings: { default: "ask", actions: { search: "allow" } },
    }),
  ];
  render(<Form taskId="task-1" />);
  expect(screen.getByText("1 allow · 1 ask · 0 blocked")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Save task" }));
  expect(mockSave).toHaveBeenLastCalledWith([
    {
      plugin_id: "plugin-1",
      action_settings: { default: "ask", actions: { search: "allow" } },
    },
  ]);
});

it("turning a plugin off and on again keeps its action settings", async () => {
  const user = setupUser();
  mockData = [
    pluginView({
      enabled: true,
      action_settings: { default: "ask", actions: { search: "allow" } },
    }),
  ];
  render(<Form taskId="task-1" />);
  const toggle = screen.getByRole("switch", {
    name: "Enable Linear for this task",
  });
  await user.click(toggle);
  await user.click(toggle);
  await user.click(screen.getByRole("button", { name: "Save task" }));
  expect(mockSave).toHaveBeenLastCalledWith([
    {
      plugin_id: "plugin-1",
      action_settings: { default: "ask", actions: { search: "allow" } },
    },
  ]);
});

it("does not offer Allow for a locked action", async () => {
  const user = setupUser();
  mockData = [
    pluginView({
      integrations: [
        {
          ...LINEAR_MCP,
          actions: LINEAR_MCP.actions.map((action) => ({
            ...action,
            locked: action.key === "create",
          })),
        },
      ],
    }),
  ];
  render(<Form />);
  await user.click(screen.getByRole("button", { name: "Manage actions" }));
  await user.click(
    screen.getByRole("combobox", { name: "Setting for Create issue" })
  );
  expect(screen.getByRole("option", { name: "Allow" })).toHaveAttribute(
    "aria-disabled",
    "true"
  );
});

it("counts a locked task Allow with the integration policy", () => {
  mockData = [
    pluginView({
      enabled: true,
      action_settings: { default: "allow", actions: {} },
      integrations: [
        {
          ...LINEAR_MCP,
          actions: LINEAR_MCP.actions.map((action) => ({
            ...action,
            locked: action.key === "create",
          })),
        },
      ],
    }),
  ];
  render(<Form taskId="task-1" />);
  expect(screen.getByText("1 allow · 1 ask · 0 blocked")).toBeInTheDocument();
});

it("sets an action to Allow, Ask, Blocked or the integration setting", async () => {
  const user = setupUser();
  render(<Form />);
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
      plugin_id: "plugin-1",
      action_settings: { default: "inherit", actions: { create: "blocked" } },
    },
  ]);
});

it("shows the sign-in reason of an integration that is not connected", () => {
  mockData = [
    pluginView({
      integrations: [
        {
          ...LINEAR_MCP,
          status: {
            state: "not_connected",
            reason: "Connect your Linear MCP account to use it.",
          },
        },
      ],
    }),
  ];
  render(<Form />);
  expect(
    screen.getByText("Connect your Linear MCP account to use it.")
  ).toBeInTheDocument();
});

it("reports a load failure without enabling the parent save", async () => {
  mockError = new Error("offline");
  render(<Form />);
  expect(
    await screen.findByText("Could not load approval settings.")
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Save task" })).toBeDisabled();
});
