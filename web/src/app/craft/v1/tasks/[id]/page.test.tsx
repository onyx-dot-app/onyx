import {
  render,
  screen,
  setupUser,
  waitFor,
  deferred,
} from "@tests/setup/test-utils";
import ScheduledTasksListPage from "@/app/craft/v1/tasks/page";
import { SWR_KEYS } from "@/lib/swr-keys";
import ScheduledTaskDetailPage from "@/app/craft/v1/tasks/[id]/page";
import type { ScheduledTaskDetail } from "@/app/craft/v1/tasks/interfaces";
import { TASKS_PATH } from "@/app/craft/v1/tasks/constants";

const mockPush = jest.fn();
const mockReplace = jest.fn();
jest.mock("next/navigation", () => ({
  useParams: () => ({ id: "task-id" }),
  useRouter: () => ({ push: mockPush, replace: mockReplace }),
  usePathname: () => "/craft/v1/tasks/task-id",
}));

const task: ScheduledTaskDetail = {
  id: "task-id",
  name: "Daily report",
  prompt: "Summarize updates",
  human_readable_schedule: "Every day",
  cron_expression: "0 9 * * *",
  editor_mode: "advanced",
  status: "ACTIVE",
  next_run_at: null,
  next_runs: [],
  last_run: null,
  pre_approved_app_ids: [],
  pre_approved_mcp_server_ids: [],
  created_at: "2026-10-19T00:00:00Z",
  updated_at: "2026-10-19T00:00:00Z",
};

afterEach(() => {
  jest.restoreAllMocks();
});

function mockRequests(deletion: Promise<Response>) {
  let listReadCount = 0;
  return jest.spyOn(global, "fetch").mockImplementation(async (url, init) => {
    if (init?.method === "DELETE") return deletion;
    if (String(url) === SWR_KEYS.scheduledTasks) {
      if (listReadCount++ === 0) {
        return new Response(
          JSON.stringify({
            items: [task, { ...task, id: "other-task", name: "Other task" }],
          })
        );
      }
      return new Promise<Response>(() => {});
    }
    return new Response(
      JSON.stringify(
        String(url).includes("/runs") ? { items: [], next_cursor: null } : task
      ),
      { status: 200 }
    );
  });
}

async function confirmDeletion() {
  const user = setupUser();
  await user.click(await screen.findByTestId("delete-button"));
  await user.click(screen.getByTestId("confirm-delete-task"));
}

test("replaces the deleted detail URL and removes the task from the cached overview", async () => {
  const fetchSpy = mockRequests(
    Promise.resolve(new Response(null, { status: 204 }))
  );
  const { rerender } = render(<ScheduledTasksListPage />);
  await screen.findByText(task.name);
  rerender(<ScheduledTaskDetailPage />);
  await confirmDeletion();
  await waitFor(() => expect(mockReplace).toHaveBeenCalledWith(TASKS_PATH));
  expect(mockPush).not.toHaveBeenCalled();
  expect(fetchSpy).toHaveBeenCalledWith(SWR_KEYS.scheduledTask(task.id), {
    method: "DELETE",
  });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

  rerender(<ScheduledTasksListPage />);
  expect(await screen.findByText("Other task")).toBeInTheDocument();
  expect(screen.queryByText(task.name)).not.toBeInTheDocument();
});

test("waits for deletion before leaving the detail page", async () => {
  const deletion = deferred<Response>();
  mockRequests(deletion.promise);
  render(<ScheduledTaskDetailPage />);
  await confirmDeletion();
  expect(mockReplace).not.toHaveBeenCalled();
  expect(mockPush).not.toHaveBeenCalled();
  expect(screen.getByTestId("confirm-delete-task")).toBeDisabled();
  deletion.resolve(new Response(null, { status: 204 }));
  await waitFor(() => expect(mockReplace).toHaveBeenCalledWith(TASKS_PATH));
});

test("keeps the detail page and allows retry when deletion fails", async () => {
  mockRequests(
    Promise.resolve(
      new Response(JSON.stringify({ detail: "Delete failed" }), { status: 500 })
    )
  );
  render(<ScheduledTaskDetailPage />);
  await confirmDeletion();
  await waitFor(() =>
    expect(screen.getByTestId("confirm-delete-task")).toBeEnabled()
  );
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  expect(mockReplace).not.toHaveBeenCalled();
  expect(mockPush).not.toHaveBeenCalled();
});
