import { render, screen, waitFor } from "@tests/setup/test-utils";
import ScheduledRunBanner from "@/sections/scheduledTasks/ScheduledRunBanner";
import { markScheduledRunViewed } from "@/lib/scheduledTasks/svc";
import type { ScheduledRunContext } from "@/lib/scheduledTasks/types";

jest.mock("@/lib/scheduledTasks/svc", () => ({
  markScheduledRunViewed: jest.fn().mockResolvedValue(undefined),
}));
jest.mock("@/lib/scheduledTasks/hooks", () => ({
  ...jest.requireActual("@/lib/scheduledTasks/hooks"),
  revalidateChatScheduledRunViews: jest.fn().mockResolvedValue(undefined),
}));

let mockRun: ScheduledRunContext | undefined;
jest.mock("swr", () => ({
  ...jest.requireActual("swr"),
  __esModule: true,
  default: () => ({ data: mockRun, mutate: jest.fn() }),
}));

function context(
  overrides: Partial<ScheduledRunContext> = {}
): ScheduledRunContext {
  return {
    run_id: "run",
    task_id: "task",
    task_name: "Daily digest",
    status: "SUCCEEDED",
    started_at: "2026-10-30T10:00:00Z",
    finished_at: "2026-10-30T10:01:00Z",
    revision: 2,
    viewed_revision: 1,
    ...overrides,
  };
}

beforeEach(() => {
  jest.mocked(markScheduledRunViewed).mockClear();
});

it("renders nothing for a chat that no task created", () => {
  mockRun = undefined;
  render(<ScheduledRunBanner chatSessionId="chat" />);
  expect(screen.queryByTestId("scheduled-run-banner")).not.toBeInTheDocument();
});

it("names the task and marks a finished run viewed once", async () => {
  mockRun = context();
  const { rerender } = render(<ScheduledRunBanner chatSessionId="chat" />);
  rerender(<ScheduledRunBanner chatSessionId="chat" />);

  expect(screen.getByText("Scheduled run of Daily digest")).toBeInTheDocument();
  await waitFor(() =>
    expect(markScheduledRunViewed).toHaveBeenCalledWith("task", "run", 2)
  );
  expect(markScheduledRunViewed).toHaveBeenCalledTimes(1);
});

it("waits until a running run stops before it marks it viewed", () => {
  mockRun = context({ status: "RUNNING" });
  render(<ScheduledRunBanner chatSessionId="chat" />);

  expect(screen.getByText("This run is in progress.")).toBeInTheDocument();
  expect(markScheduledRunViewed).not.toHaveBeenCalled();
});

it("marks a run that waits for approval viewed", async () => {
  mockRun = context({ status: "AWAITING_APPROVAL" });
  render(<ScheduledRunBanner chatSessionId="chat" />);

  expect(
    screen.getByText("This run waits for your approval below.")
  ).toBeInTheDocument();
  await waitFor(() => expect(markScheduledRunViewed).toHaveBeenCalled());
});
