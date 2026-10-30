import { render, screen, waitFor } from "@tests/setup/test-utils";
import userEvent from "@testing-library/user-event";
import RunHistoryTable from "@/app/craft/v1/tasks/components/RunHistoryTable";
import {
  listScheduledTaskRuns,
  markScheduledRunsViewed,
} from "@/app/craft/v1/tasks/api";
import type { ScheduledRunSummary } from "@/app/craft/v1/tasks/types";

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn() }),
}));
jest.mock("@/app/craft/v1/tasks/api", () => ({
  listScheduledTaskRuns: jest.fn(),
  markScheduledRunsViewed: jest.fn(),
}));
jest.mock("@/lib/scheduledTasks/hooks", () => ({
  revalidateScheduledRunViews: jest.fn().mockResolvedValue(undefined),
}));

function run(
  id: string,
  revision: number,
  viewed_revision: number | null
): ScheduledRunSummary {
  return {
    id,
    status: "SUCCEEDED",
    trigger_source: "SCHEDULED",
    started_at: "2026-10-30T10:00:00Z",
    finished_at: "2026-10-30T10:01:00Z",
    session_id: `session-${id}`,
    summary: `Summary ${id}`,
    skip_reason: null,
    error_class: null,
    revision,
    viewed_revision,
  };
}

let mockRuns: ScheduledRunSummary[] = [];
let mockUnviewedRuns: ScheduledRunSummary[] = [];
jest.mock("swr", () => ({
  ...jest.requireActual("swr"),
  __esModule: true,
  default: (key: string) => ({
    data: {
      items: key.includes("unviewed=true") ? mockUnviewedRuns : mockRuns,
      next_cursor: null,
    },
    error: undefined,
    isLoading: false,
    mutate: jest.fn(),
  }),
}));

beforeEach(() => {
  jest.mocked(markScheduledRunsViewed).mockReset();
  jest.mocked(listScheduledTaskRuns).mockReset();
  mockUnviewedRuns = [];
});

it("marks every unviewed run of the task, not only loaded rows", async () => {
  mockRuns = [run("new", 2, 1), run("seen", 1, 1)];
  const unloaded = run("unloaded", 1, null);
  jest
    .mocked(listScheduledTaskRuns)
    .mockResolvedValue({ items: [mockRuns[0]!, unloaded], next_cursor: null });
  jest
    .mocked(markScheduledRunsViewed)
    .mockResolvedValue({ items: [run("new", 2, 2)], next_cursor: null });
  render(<RunHistoryTable taskId="task" />);

  expect(screen.getAllByRole("img", { name: "New results" })).toHaveLength(1);
  await userEvent.click(
    screen.getByRole("button", { name: "Mark all viewed" })
  );

  await waitFor(() =>
    expect(markScheduledRunsViewed).toHaveBeenCalledWith("task", [
      mockRuns[0],
      unloaded,
    ])
  );
  expect(listScheduledTaskRuns).toHaveBeenCalledWith("task", {
    limit: 100,
    unviewed: true,
  });
});

it("disables mark all viewed when every run was opened", () => {
  mockRuns = [run("seen", 1, 1), run("skipped", 0, null)];
  render(<RunHistoryTable taskId="task" />);

  expect(
    screen.queryByRole("img", { name: "New results" })
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Mark all viewed" })
  ).toBeDisabled();
});

it("enables mark all viewed when only an unloaded run is unviewed", () => {
  mockRuns = [run("seen", 1, 1)];
  mockUnviewedRuns = [run("older", 1, null)];
  render(<RunHistoryTable taskId="task" />);

  expect(screen.getByRole("button", { name: "Mark all viewed" })).toBeEnabled();
});
