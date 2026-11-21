import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import ScheduledTaskEditor from "@/sections/scheduledTasks/ScheduledTaskEditor";
import { createScheduledTask } from "@/lib/scheduledTasks/svc";

jest.mock("next/navigation", () => ({
  ...jest.requireActual<typeof import("@tests/setup/mocks/nextNavigation")>(
    "@tests/setup/mocks/nextNavigation"
  ).nextNavigationMock,
  useRouter: () => ({ replace: jest.fn() }),
}));
jest.mock("@/lib/scheduledTasks/svc", () => ({
  createScheduledTask: jest.fn(),
  updateScheduledTask: jest.fn(),
}));
jest.mock("@/lib/scheduledTasks/hooks", () => ({
  revalidateChatScheduledRunViews: jest.fn().mockResolvedValue(undefined),
}));
jest.mock("swr", () => ({
  ...jest.requireActual("swr"),
  __esModule: true,
  default: () => ({ data: undefined, error: undefined, isLoading: false }),
  mutate: jest.fn().mockResolvedValue(undefined),
}));
jest.mock("@/app/craft/v1/tasks/components/ScheduleEditor", () => ({
  __esModule: true,
  default: () => null,
}));
const mockPolicyUrls: string[] = [];
jest.mock("@/app/craft/v1/tasks/components/TaskActionPolicies", () => ({
  __esModule: true,
  default: function MockPolicies({
    onChange,
    url,
  }: {
    onChange: (value: unknown[]) => void;
    url: string;
  }) {
    const { useEffect } = jest.requireActual("react");
    mockPolicyUrls.push(url);
    useEffect(() => onChange([]), [onChange]);
    return null;
  },
}));

beforeEach(() => {
  window.history.replaceState(null, "", "/app/scheduled-tasks/new");
});

it("creates a task with every integration off and runs it", async () => {
  const user = setupUser();
  jest.mocked(createScheduledTask).mockResolvedValue({
    id: "task",
    name: "Digest",
    prompt: "Summarize",
    cron_expression: "0 */1 * * *",
    editor_mode: "interval",
    status: "ACTIVE",
    next_run_at: null,
    next_runs: [],
    last_run: null,
    unviewed_run_count: 0,
    integrations: [],
  });
  render(<ScheduledTaskEditor />);

  await user.type(screen.getByTestId("scheduled-task-name"), " Digest ");
  await user.type(screen.getByTestId("scheduled-task-prompt"), "Summarize");
  await user.click(screen.getByTestId("save-and-run-scheduled-task"));

  await waitFor(() =>
    expect(createScheduledTask).toHaveBeenCalledWith({
      name: "Digest",
      prompt: "Summarize",
      editor_mode: "interval",
      editor_payload: { unit: "hours", every: 1 },
      integrations: [],
      run_immediately: true,
    })
  );
  expect(mockPolicyUrls).toContain("/api/scheduled-tasks/action-policies");
  await waitFor(() =>
    expect(window.location.pathname).toBe("/app/scheduled-tasks/task")
  );
});
