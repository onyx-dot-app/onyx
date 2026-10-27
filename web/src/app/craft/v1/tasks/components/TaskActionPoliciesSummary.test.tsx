import { render, screen } from "@tests/setup/test-utils";
import TaskActionPoliciesSummary from "@/app/craft/v1/tasks/components/TaskActionPoliciesSummary";
import type { AppActionPoliciesView } from "@/lib/plugins/types";

const initialData: AppActionPoliciesView[] = [
  {
    gated_app_id: 1,
    kind: "external_app",
    target_id: 10,
    name: "Slack",
    enabled: true,
    users_can_manage_policies: true,
    actions: [],
  },
];
let mockData = initialData;
jest.mock("swr", () => ({
  ...jest.requireActual("swr"),
  __esModule: true,
  default: () => ({ data: mockData, mutate: jest.fn() }),
}));
beforeEach(() => {
  mockData = initialData;
});

it("lists only enabled plugins as passive task context", () => {
  mockData = [
    ...initialData.map((app) => ({ ...app, enabled: true })),
    ...initialData.map((app) => ({
      ...app,
      gated_app_id: 2,
      name: "Disabled plugin",
      enabled: false,
    })),
  ];
  render(<TaskActionPoliciesSummary taskId="task" />);
  expect(screen.getByText("Slack")).toBeInTheDocument();
  expect(screen.queryByText("Disabled plugin")).not.toBeInTheDocument();
  expect(screen.queryByRole("switch")).not.toBeInTheDocument();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

it("shows an explicit empty state when no plugins are enabled", () => {
  mockData = initialData.map((app) => ({ ...app, enabled: false }));
  render(<TaskActionPoliciesSummary taskId="task" />);
  expect(
    screen.getByText("No plugins enabled for this task.")
  ).toBeInTheDocument();
  expect(screen.queryByText("Slack")).not.toBeInTheDocument();
});
