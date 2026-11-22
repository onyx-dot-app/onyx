import { render, screen } from "@tests/setup/test-utils";
import TaskActionPoliciesSummary from "@/app/craft/v1/tasks/components/TaskActionPoliciesSummary";
import type { TaskIntegrationView } from "@/app/craft/v1/tasks/types";

function integration(
  id: number,
  name: string,
  enabled: boolean
): TaskIntegrationView {
  return {
    id,
    name,
    kind: "mcp",
    app_type: null,
    status: { state: "connected", reason: null },
    actions: [],
    enabled,
    action_settings: enabled ? { default: "inherit", actions: {} } : null,
    runnable: true,
  };
}

let mockData: TaskIntegrationView[] = [];
jest.mock("swr", () => ({
  ...jest.requireActual("swr"),
  __esModule: true,
  default: () => ({ data: mockData, mutate: jest.fn() }),
}));

it("lists only enabled integrations as passive task context", () => {
  mockData = [
    integration(1, "Slack", true),
    integration(2, "Disabled app", false),
  ];
  render(<TaskActionPoliciesSummary taskId="task" />);
  expect(screen.getByText("Slack")).toBeInTheDocument();
  expect(screen.queryByText("Disabled app")).not.toBeInTheDocument();
  expect(screen.queryByRole("switch")).not.toBeInTheDocument();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

it("shows an explicit empty state when no integrations are enabled", () => {
  mockData = [integration(1, "Slack", false)];
  render(<TaskActionPoliciesSummary taskId="task" />);
  expect(
    screen.getByText("No integrations turned on for this task.")
  ).toBeInTheDocument();
  expect(screen.queryByText("Slack")).not.toBeInTheDocument();
});
