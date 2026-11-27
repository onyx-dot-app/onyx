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
  revalidateScheduledRunViews: jest.fn().mockResolvedValue(undefined),
}));
jest.mock("swr", () => ({
  ...jest.requireActual("swr"),
  __esModule: true,
  default: () => ({ data: undefined, error: undefined, isLoading: false }),
  mutate: jest.fn().mockResolvedValue(undefined),
}));
// Switches modes as the real editor does: the mode first, then a default
// payload for the new mode.
jest.mock("@/app/craft/v1/tasks/components/ScheduleEditor", () => ({
  __esModule: true,
  default: function MockScheduleEditor({
    payload,
    onModeChange,
    onPayloadChange,
  }: {
    payload: unknown;
    onModeChange: (mode: string) => void;
    onPayloadChange: (payload: unknown) => void;
  }) {
    return (
      <>
        <output data-testid="schedule-payload">
          {JSON.stringify(payload)}
        </output>
        <button onClick={() => onPayloadChange({ unit: "minutes", every: 15 })}>
          every 15 minutes
        </button>
        <button
          onClick={() => {
            onModeChange("daily_weekly");
            onPayloadChange({ weekdays: [1], time: "09:00" });
          }}
        >
          daily
        </button>
        <button
          onClick={() => {
            onModeChange("interval");
            onPayloadChange({ unit: "hours", every: 1 });
          }}
        >
          interval
        </button>
      </>
    );
  },
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
    integrations: [],
    human_readable_schedule: "Every hour",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
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

it("keeps a mode's schedule when the user switches modes and back", async () => {
  const user = setupUser();
  render(<ScheduledTaskEditor />);

  await user.click(screen.getByRole("button", { name: "every 15 minutes" }));
  await user.click(screen.getByRole("button", { name: "daily" }));
  expect(screen.getByTestId("schedule-payload")).toHaveTextContent(
    JSON.stringify({ weekdays: [1], time: "09:00" })
  );
  await user.click(screen.getByRole("button", { name: "interval" }));

  expect(screen.getByTestId("schedule-payload")).toHaveTextContent(
    JSON.stringify({ unit: "minutes", every: 15 })
  );
});

it("says when a name is too long and does not save", async () => {
  const user = setupUser();
  render(<ScheduledTaskEditor />);

  const name = screen.getByTestId("scheduled-task-name");
  await user.click(name);
  await user.paste("x".repeat(201));
  await user.type(screen.getByTestId("scheduled-task-prompt"), "Summarize");

  expect(screen.getByText("Use 200 characters or fewer.")).toBeInTheDocument();
  expect(screen.getByTestId("save-scheduled-task")).toBeDisabled();
});

it("counts an emoji in a name as one character, as the server does", async () => {
  const user = setupUser();
  render(<ScheduledTaskEditor />);

  await user.click(screen.getByTestId("scheduled-task-name"));
  await user.paste("😀".repeat(200));
  await user.type(screen.getByTestId("scheduled-task-prompt"), "Summarize");

  expect(
    screen.queryByText("Use 200 characters or fewer.")
  ).not.toBeInTheDocument();
});

it("locks the form while a save is pending", async () => {
  const user = setupUser();
  jest.mocked(createScheduledTask).mockReturnValue(new Promise(() => {}));
  render(<ScheduledTaskEditor />);

  expect(screen.getByTestId("scheduled-task-form")).not.toHaveAttribute(
    "inert"
  );
  await user.type(screen.getByTestId("scheduled-task-name"), "Digest");
  await user.type(screen.getByTestId("scheduled-task-prompt"), "Summarize");
  await user.click(screen.getByTestId("save-scheduled-task"));

  expect(screen.getByTestId("scheduled-task-form")).toHaveAttribute("inert");
});
