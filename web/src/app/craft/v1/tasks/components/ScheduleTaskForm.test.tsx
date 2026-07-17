import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import ScheduleTaskForm, {
  defaultFormInitial,
} from "@/app/craft/v1/tasks/components/ScheduleTaskForm";
import type { PickerEntry } from "@/lib/skills/picker";

const mockRouterPush = jest.fn();

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockRouterPush }),
}));

jest.mock("@/hooks/useUserSkills", () => ({
  __esModule: true,
  default: () => ({ data: { builtins: [], customs: [] } }),
}));

jest.mock("@/hooks/useUserExternalApps", () => ({
  __esModule: true,
  default: () => ({ data: [] }),
}));

jest.mock("@/app/craft/v1/tasks/components/ScheduleEditor", () => ({
  __esModule: true,
  default: () => null,
}));

jest.mock("@/app/craft/v1/tasks/components/PreApprovalPicker", () => ({
  __esModule: true,
  default: () => null,
}));

jest.mock("@/sections/input/EntryPickerPopover", () => ({
  __esModule: true,
  default: ({
    open,
    onSelect,
  }: {
    open: boolean;
    onSelect: (entry: PickerEntry) => void;
  }) =>
    open ? (
      <div>
        <button
          type="button"
          onClick={() =>
            onSelect({
              kind: "app",
              slug: "slack",
              name: "Slack",
              description: "Search Slack",
              appType: "SLACK",
              authenticated: true,
            })
          }
        >
          Select connected Slack
        </button>
        <button
          type="button"
          onClick={() =>
            onSelect({
              kind: "app",
              slug: "gmail",
              name: "Gmail",
              description: "Search Gmail",
              appType: "GMAIL",
              authenticated: false,
            })
          }
        >
          Connect Gmail
        </button>
      </div>
    ) : null,
}));

function renderForm() {
  render(
    <ScheduleTaskForm
      initial={defaultFormInitial()}
      isEdit={false}
      title="Create scheduled task"
      onBack={jest.fn()}
    />
  );
}

describe("ScheduleTaskForm app picker", () => {
  it("inserts an authenticated app into the task prompt", async () => {
    const user = setupUser();
    renderForm();

    const prompt = screen.getByTestId("task-prompt-input");
    await user.type(prompt, "/");
    await user.click(
      screen.getByRole("button", { name: "Select connected Slack" })
    );

    await waitFor(() => expect(prompt).toHaveValue("/slack "));
    expect(mockRouterPush).not.toHaveBeenCalled();
  });

  it("routes an unauthenticated app to connection without inserting it", async () => {
    const user = setupUser();
    renderForm();

    const prompt = screen.getByTestId("task-prompt-input");
    await user.type(prompt, "/");
    await user.click(screen.getByRole("button", { name: "Connect Gmail" }));

    expect(mockRouterPush).toHaveBeenCalledWith("/craft/v1/apps?connect=gmail");
    expect(prompt).toHaveValue("/");
  });
});
