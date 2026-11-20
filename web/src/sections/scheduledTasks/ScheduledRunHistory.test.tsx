import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import ScheduledRunHistory from "@/sections/scheduledTasks/ScheduledRunHistory";
import {
  listScheduledTaskRuns,
  markScheduledRunsViewed,
} from "@/lib/scheduledTasks/svc";
import type {
  ScheduledRunListResponse,
  ScheduledRunSummary,
} from "@/lib/scheduledTasks/types";

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

// The runs the fake server holds, newest first. A page ends with a cursor
// when more runs follow it.
let serverRuns: ScheduledRunSummary[] = [];
let pageSize = 50;

function serve(url: string): ScheduledRunListResponse {
  const query = new URL(url, "http://localhost").searchParams;
  if (query.get("unviewed") === "true") return { items: [], next_cursor: null };
  const cursor = query.get("cursor");
  const start = cursor
    ? serverRuns.findIndex((candidate) => candidate.id === cursor) + 1
    : 0;
  const items = serverRuns.slice(start, start + pageSize);
  const last = items[items.length - 1];
  return {
    items,
    next_cursor: last && start + pageSize < serverRuns.length ? last.id : null,
  };
}

beforeAll(() => {
  global.fetch = jest.fn(async (input: RequestInfo | URL) => {
    const body = serve(String(input));
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }) as typeof fetch;
});

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
  pageSize = 50;
  window.history.replaceState(null, "", "/app/scheduled-tasks/task");
  mockReplace.mockReset();
  jest.mocked(listScheduledTaskRuns).mockReset();
  jest.mocked(markScheduledRunsViewed).mockReset();
});

it("opens a run's chat and leaves a run without a chat closed", async () => {
  const user = setupUser();
  serverRuns = [
    run("chat", { status: "CANCELLED", error_class: "approval_timeout" }),
    run("closed", { chat_session_id: null }),
  ];
  render(<ScheduledRunHistory taskId="task" />);

  expect(await screen.findByText("Cancelled")).toBeInTheDocument();
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
  serverRuns = [unviewed, run("seen")];
  jest
    .mocked(listScheduledTaskRuns)
    .mockResolvedValue({ items: [unviewed], next_cursor: null });
  jest
    .mocked(markScheduledRunsViewed)
    .mockResolvedValue({ items: [], next_cursor: null });
  render(<ScheduledRunHistory taskId="task" />);

  expect(
    await screen.findAllByRole("img", { name: "New results" })
  ).toHaveLength(1);
  await user.click(screen.getByRole("button", { name: "Mark all viewed" }));

  await waitFor(() =>
    expect(markScheduledRunsViewed).toHaveBeenCalledWith("task", [unviewed])
  );
  expect(listScheduledTaskRuns).toHaveBeenCalledWith("task", {
    limit: 100,
    unviewed: true,
  });
});

it("keeps updating a run that a new run pushes off the first page", async () => {
  const user = setupUser();
  pageSize = 2;
  const at = (hour: number) =>
    `2026-10-30T${String(hour).padStart(2, "0")}:00:00Z`;
  const pushed = run("one", {
    started_at: at(1),
    status: "RUNNING",
    summary: "first run",
  });
  serverRuns = [
    // Unviewed, so Mark all viewed can refresh the history.
    run("two", {
      started_at: at(2),
      summary: "second run",
      revision: 1,
      viewed_revision: null,
    }),
    pushed,
    run("zero", { started_at: at(0), summary: "oldest run" }),
  ];
  jest
    .mocked(listScheduledTaskRuns)
    .mockResolvedValue({ items: [], next_cursor: null });
  render(<ScheduledRunHistory taskId="task" />);
  await screen.findByText("first run");
  await user.click(screen.getByRole("button", { name: "Load more" }));
  await screen.findByText("oldest run");

  // A new run arrives, and the run it pushes off the first page finishes.
  serverRuns = [
    run("three", {
      started_at: at(3),
      summary: "newest run",
      revision: 1,
      viewed_revision: null,
    }),
    run("two", { started_at: at(2), summary: "second run" }),
    { ...pushed, status: "SUCCEEDED", summary: "first run done" },
    run("zero", { started_at: at(0), summary: "oldest run" }),
  ];
  await user.click(screen.getByRole("button", { name: "Mark all viewed" }));

  await waitFor(() =>
    expect(
      screen.getAllByText(/run( done)?$/).map((cell) => cell.textContent)
    ).toEqual(["newest run", "second run", "first run done", "oldest run"])
  );
});
