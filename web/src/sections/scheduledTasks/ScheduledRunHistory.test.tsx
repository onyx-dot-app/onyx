import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import ScheduledRunHistory from "@/sections/scheduledTasks/ScheduledRunHistory";
import {
  listScheduledTaskRuns,
  markScheduledRunsViewed,
} from "@/lib/scheduledTasks/svc";
import type { ScheduledRunSummary } from "@/lib/scheduledTasks/types";

const mockReplace = jest.fn();
jest.mock("next/navigation", () => ({
  ...jest.requireActual<typeof import("@tests/setup/mocks/nextNavigation")>(
    "@tests/setup/mocks/nextNavigation"
  ).nextNavigationMock,
  useRouter: () => ({ replace: mockReplace }),
}));
jest.mock("@/lib/scheduledTasks/svc", () => ({
  listScheduledTaskRuns: jest.fn(),
  markScheduledRunsViewed: jest.fn(),
}));
jest.mock("@/lib/scheduledTasks/hooks", () => ({
  ...jest.requireActual("@/lib/scheduledTasks/hooks"),
  revalidateChatScheduledRunViews: jest.fn().mockResolvedValue(undefined),
}));

let mockRuns: ScheduledRunSummary[] = [];
jest.mock("swr", () => ({
  ...jest.requireActual("swr"),
  __esModule: true,
  default: (key: string) => ({
    data: {
      items: key.includes("unviewed=true") ? [] : mockRuns,
      next_cursor: null,
    },
    error: undefined,
    isLoading: false,
  }),
}));

function run(
  id: string,
  overrides: Partial<ScheduledRunSummary> = {}
): ScheduledRunSummary {
  return {
    id,
    status: "SUCCEEDED",
    trigger_source: "SCHEDULED",
    started_at: "2026-10-30T10:00:00Z",
    finished_at: "2026-10-30T10:01:00Z",
    chat_session_id: `chat-${id}`,
    summary: null,
    skip_reason: null,
    error_class: null,
    revision: 1,
    viewed_revision: 1,
    ...overrides,
  };
}

beforeEach(() => {
  window.history.replaceState(null, "", "/app/scheduled-tasks/task");
  mockReplace.mockReset();
  jest.mocked(listScheduledTaskRuns).mockReset();
  jest.mocked(markScheduledRunsViewed).mockReset();
});

it("opens a run's chat and leaves a Craft run closed", async () => {
  const user = setupUser();
  mockRuns = [
    run("chat", { status: "CANCELLED", error_class: "approval_timeout" }),
    run("craft", { chat_session_id: null }),
  ];
  render(<ScheduledRunHistory taskId="task" />);

  expect(screen.getByText("Cancelled")).toBeInTheDocument();
  expect(
    screen.getByText("Cancelled: nobody answered the approval within 24 hours.")
  ).toBeInTheDocument();

  const rows = screen.getAllByRole("row").slice(1);
  await user.click(rows[1]!);
  expect(mockReplace).not.toHaveBeenCalled();

  await user.click(rows[0]!);
  await waitFor(() =>
    expect(window.location.pathname + window.location.search).toBe(
      "/app?chatId=chat-chat"
    )
  );
});

it("marks every unviewed run viewed", async () => {
  const user = setupUser();
  const unviewed = run("new", { revision: 2, viewed_revision: 1 });
  mockRuns = [unviewed, run("seen")];
  jest
    .mocked(listScheduledTaskRuns)
    .mockResolvedValue({ items: [unviewed], next_cursor: null });
  jest
    .mocked(markScheduledRunsViewed)
    .mockResolvedValue({ items: [], next_cursor: null });
  render(<ScheduledRunHistory taskId="task" />);

  expect(screen.getAllByRole("img", { name: "New results" })).toHaveLength(1);
  await user.click(screen.getByRole("button", { name: "Mark all viewed" }));

  await waitFor(() =>
    expect(markScheduledRunsViewed).toHaveBeenCalledWith("task", [unviewed])
  );
  expect(listScheduledTaskRuns).toHaveBeenCalledWith("task", {
    limit: 100,
    unviewed: true,
  });
});
