import { render, screen } from "@tests/setup/test-utils";
import TaskActionPoliciesSummary from "@/app/craft/v1/tasks/components/TaskActionPoliciesSummary";
import type { TaskPluginView } from "@/app/craft/v1/tasks/types";

function plugin(
  pluginId: string,
  name: string,
  enabled: boolean
): TaskPluginView {
  return {
    plugin_id: pluginId,
    plugin_name: name,
    enabled,
    action_settings: enabled ? { default: "inherit", actions: {} } : null,
    integrations: [],
  };
}

let mockData: TaskPluginView[] = [];
jest.mock("swr", () => ({
  ...jest.requireActual("swr"),
  __esModule: true,
  default: () => ({ data: mockData, mutate: jest.fn() }),
}));

it("lists only enabled plugins as passive task context", () => {
  mockData = [
    plugin("a", "Slack", true),
    plugin("b", "Disabled plugin", false),
  ];
  render(<TaskActionPoliciesSummary taskId="task" />);
  expect(screen.getByText("Slack")).toBeInTheDocument();
  expect(screen.queryByText("Disabled plugin")).not.toBeInTheDocument();
  expect(screen.queryByRole("switch")).not.toBeInTheDocument();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

it("shows an explicit empty state when no plugins are enabled", () => {
  mockData = [plugin("a", "Slack", false)];
  render(<TaskActionPoliciesSummary taskId="task" />);
  expect(
    screen.getByText("No plugins enabled for this task.")
  ).toBeInTheDocument();
  expect(screen.queryByText("Slack")).not.toBeInTheDocument();
});
