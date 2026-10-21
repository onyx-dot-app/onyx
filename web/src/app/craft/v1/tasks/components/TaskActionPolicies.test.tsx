import { useState } from "react";
import { render, screen, setupUser, within } from "@tests/setup/test-utils";
import TaskActionPolicies, {
  TaskActionPoliciesSummary,
} from "@/app/craft/v1/tasks/components/TaskActionPolicies";
import type {
  AppActionPoliciesView,
  TaskAppActionPolicies,
} from "@/lib/plugins/types";

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn() }),
  usePathname: () => "/craft/v1/apps",
}));

const mockExternalApps = [{ id: 10, authenticated: false }];
jest.mock("@/hooks/useUserExternalApps", () => ({
  __esModule: true,
  default: () => ({ data: mockExternalApps }),
}));
jest.mock("@/lib/mcp/hooks", () => ({
  useCraftMcpServers: () => ({ data: { mcp_servers: [] } }),
}));

const initialData: AppActionPoliciesView[] = [
  {
    gated_app_id: 1,
    kind: "external_app",
    target_id: 10,
    name: "Slack",
    users_can_manage_policies: true,
    enabled: null,
    actions: [
      {
        action_id: "send",
        normalised_name: "Send messages",
        description: "",
        effective_policy: "ALWAYS",
        workspace_policy: "ASK",
        stored_policy: "ALWAYS",
        editable: true,
        lock_reason: null,
      },
      {
        action_id: "delete",
        normalised_name: "Delete messages",
        description: "",
        effective_policy: "DENY",
        workspace_policy: "DENY",
        stored_policy: null,
        editable: false,
        lock_reason: "workspace_disabled",
      },
    ],
  },
];
let mockData = initialData;
let mockError: Error | undefined;
let mockIsValidating = false;
const mockSave = jest.fn();
jest.mock("swr", () => ({
  ...jest.requireActual("swr"),
  __esModule: true,
  default: (
    _key: string,
    _fetcher: unknown,
    options?: { onSuccess?: (app: AppActionPoliciesView[]) => void }
  ) => {
    const React = jest.requireActual<typeof import("react")>("react");
    React.useEffect(() => {
      if (!mockIsValidating && !mockError) options?.onSuccess?.(mockData);
    }, [mockData, mockIsValidating, mockError]);
    return {
      data: mockError ? undefined : mockData,
      error: mockError,
      isValidating: mockIsValidating,
      mutate: jest.fn(),
    };
  },
}));
function Form({ taskId = null }: { taskId?: string | null }) {
  const [value, setValue] = useState<TaskAppActionPolicies[] | null>(null);
  return (
    <>
      <TaskActionPolicies taskId={taskId} value={value} onChange={setValue} />
      <button disabled={value === null} onClick={() => mockSave(value)}>
        Save task
      </button>
    </>
  );
}
beforeEach(() => {
  mockData = initialData;
  mockError = undefined;
  mockIsValidating = false;
  mockSave.mockClear();
});
it("copies personal settings once, retains task edits, and locks workspace-disabled actions", async () => {
  const user = setupUser();
  const { rerender } = render(<Form />);
  await user.click(
    screen.getByRole("switch", { name: "Enable Slack for this task" })
  );
  await user.click(screen.getByRole("button", { name: "Manage actions" }));
  const send = within(screen.getByRole("group", { name: "Send messages" }));
  expect(send.getByRole("button", { name: "Auto-approve" })).toHaveAttribute(
    "aria-pressed",
    "true"
  );
  for (const button of within(
    screen.getByRole("group", { name: "Delete messages" })
  ).getAllByRole("button"))
    expect(button).toBeDisabled();
  await user.click(send.getByRole("button", { name: "Ask" }));
  await user.click(screen.getByRole("button", { name: "Save changes" }));
  rerender(<Form />);
  await user.click(screen.getByRole("button", { name: "Save task" }));
  expect(mockSave).toHaveBeenCalledWith([
    {
      gated_app_id: 1,
      enabled: true,
      action_policies: { send: "ASK", delete: "DENY" },
    },
  ]);
  expect(screen.getByRole("button", { name: "Save task" })).toBeEnabled();
});
it("reports a load failure without enabling the parent save", async () => {
  mockError = new Error("offline");
  render(<Form />);
  expect(
    await screen.findByText("Could not load approval settings.")
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Save task" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Try again" })).toBeEnabled();
});

it("keeps the reviewed catalog when a background refresh adds an app", async () => {
  const user = setupUser();
  const { rerender } = render(<Form />);
  await user.click(
    screen.getByRole("switch", { name: "Enable Slack for this task" })
  );
  const original = initialData[0];
  if (!original) throw new Error("Missing fixture app");
  mockData = [
    ...initialData,
    { ...original, gated_app_id: 99, name: "New app" },
  ];
  rerender(<Form />);
  expect(screen.queryByText("New app")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Save task" }));
  expect(mockSave).toHaveBeenCalledWith([
    {
      gated_app_id: 1,
      enabled: true,
      action_policies: { send: "ALWAYS", delete: "DENY" },
    },
  ]);
});

it("keeps a complete draft editable after a background fetch fails", async () => {
  const user = setupUser();
  const { rerender } = render(<Form />);
  await user.click(
    screen.getByRole("switch", { name: "Enable Slack for this task" })
  );
  mockError = new Error("offline");
  rerender(<Form />);
  expect(screen.getByRole("button", { name: "Save task" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "Manage actions" })).toBeEnabled();
  expect(
    screen.queryByText("Could not load approval settings.")
  ).not.toBeInTheDocument();
});
it("shows a compact task summary with read-only action details", async () => {
  const user = setupUser();
  mockData = initialData.map((app) => ({ ...app, enabled: true }));
  render(<TaskActionPoliciesSummary taskId="task" />);
  expect(
    screen.getByRole("switch", { name: "Enable Slack for this task" })
  ).toBeChecked();
  expect(
    screen.getByText("1 auto-approve · 0 ask · 1 disabled")
  ).toBeInTheDocument();
  expect(screen.queryByText("Send messages")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "View actions" }));
  expect(screen.getByText("Send messages")).toBeInTheDocument();
  expect(
    within(screen.getByRole("group", { name: "Send messages" })).getByRole(
      "button",
      { name: "Auto-approve" }
    )
  ).toBeDisabled();
  expect(
    screen.queryByRole("button", { name: "Save changes" })
  ).not.toBeInTheDocument();
});
it("starts new apps off without copying actions until enabled", async () => {
  const user = setupUser();
  render(<Form />);
  expect(
    screen.getByRole("switch", { name: "Enable Slack for this task" })
  ).not.toBeChecked();
  expect(screen.queryByText("Disabled for this task")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Manage actions" })
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("group", { name: "Send messages" })
  ).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Save task" }));
  expect(mockSave).toHaveBeenCalledWith([
    { gated_app_id: 1, enabled: false, action_policies: {} },
  ]);
});
it("preserves edited choices when an app is disabled and enabled again", async () => {
  const user = setupUser();
  render(<Form />);
  const toggle = screen.getByRole("switch", {
    name: "Enable Slack for this task",
  });
  await user.click(toggle);
  await user.click(screen.getByRole("button", { name: "Manage actions" }));
  await user.click(
    within(screen.getByRole("group", { name: "Send messages" })).getByRole(
      "button",
      { name: "Ask" }
    )
  );
  await user.click(screen.getByRole("button", { name: "Save changes" }));
  await user.click(toggle);
  expect(
    screen.queryByRole("group", { name: "Send messages" })
  ).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Save task" }));
  expect(mockSave).toHaveBeenCalledWith([
    {
      gated_app_id: 1,
      enabled: false,
      action_policies: { send: "ASK", delete: "DENY" },
    },
  ]);
  await user.click(toggle);
  await user.click(screen.getByRole("button", { name: "Manage actions" }));
  expect(
    within(screen.getByRole("group", { name: "Send messages" })).getByRole(
      "button",
      { name: "Ask" }
    )
  ).toHaveAttribute("aria-pressed", "true");
});
it("loads an existing task's enabled apps and independent stored choices", async () => {
  const user = setupUser();
  mockData = initialData.map((app) => ({
    ...app,
    enabled: true,
    actions: app.actions.map((action) => ({
      ...action,
      stored_policy: "ASK",
      effective_policy: "ASK",
    })),
  }));
  render(<Form taskId="task" />);
  expect(
    screen.getByRole("switch", { name: "Enable Slack for this task" })
  ).toBeChecked();
  await user.click(screen.getByRole("button", { name: "Manage actions" }));
  expect(
    within(screen.getByRole("group", { name: "Send messages" })).getByRole(
      "button",
      { name: "Ask" }
    )
  ).toHaveAttribute("aria-pressed", "true");
});

it("shows missing credentials without preventing task enablement", async () => {
  const user = setupUser();
  render(<Form />);
  expect(await screen.findByText("Connection required")).toBeInTheDocument();
  const toggle = screen.getByRole("switch", {
    name: "Enable Slack for this task",
  });
  await user.click(toggle);
  expect(toggle).toBeChecked();
  expect(screen.getByText("Connection required")).toBeInTheDocument();
});

it("keeps hundreds of actions out of the form and applies filtered edits only after Save", async () => {
  const user = setupUser();
  const original = initialData[0];
  if (!original) throw new Error("Missing fixture app");
  mockData = [
    {
      ...original,
      actions: [
        ...original.actions,
        ...Array.from({ length: 200 }, (_, index) => ({
          action_id: `read-${index}`,
          normalised_name: `Read record ${index}`,
          description: "Read records",
          effective_policy: "ASK" as const,
          workspace_policy: "ASK" as const,
          stored_policy: null,
          editable: true,
          lock_reason: null,
        })),
      ],
    },
  ];
  render(<Form />);
  await user.click(
    screen.getByRole("switch", { name: "Enable Slack for this task" })
  );
  expect(screen.queryByText("Read record 199")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Manage actions" }));
  await user.type(
    screen.getByRole("textbox", { name: "Search tools" }),
    "Send messages"
  );
  expect(screen.queryByText("Read record 199")).not.toBeInTheDocument();
  await user.click(screen.getByRole("combobox", { name: "Set permissions" }));
  await user.keyboard("{ArrowDown}{ArrowDown}{Enter}");
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  await user.click(screen.getByRole("button", { name: "Discard changes" }));
  expect(
    screen.getByText("1 auto-approve · 200 ask · 1 disabled")
  ).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Manage actions" }));
  await user.type(
    screen.getByRole("textbox", { name: "Search tools" }),
    "Send messages"
  );
  await user.click(screen.getByRole("combobox", { name: "Set permissions" }));
  await user.keyboard("{ArrowDown}{ArrowDown}{Enter}");
  await user.click(screen.getByRole("button", { name: "Save changes" }));
  expect(
    screen.getByText("0 auto-approve · 201 ask · 1 disabled")
  ).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Save task" }));
  expect(mockSave).toHaveBeenCalledWith([
    expect.objectContaining({
      action_policies: expect.objectContaining({
        send: "ASK",
        delete: "DENY",
        "read-199": "ASK",
      }),
    }),
  ]);
});

it("searches actions and keeps workspace-disabled actions out of bulk edits", async () => {
  const user = setupUser();
  render(<Form />);
  await user.click(
    screen.getByRole("switch", { name: "Enable Slack for this task" })
  );
  await user.click(screen.getByRole("button", { name: "Manage actions" }));
  await user.type(
    screen.getByRole("textbox", { name: "Search tools" }),
    "Delete messages"
  );
  expect(screen.queryByText("Send messages")).not.toBeInTheDocument();
  expect(screen.getByText("Delete messages")).toBeInTheDocument();
  expect(screen.getByText("1 tool")).toBeInTheDocument();
  await user.click(screen.getByRole("combobox", { name: "Set permissions" }));
  expect(screen.getByRole("option", { name: "Auto-approve" })).toHaveAttribute(
    "aria-disabled",
    "true"
  );
});

it("resets all editable actions to workspace defaults even when search hides them", async () => {
  const user = setupUser();
  const original = initialData[0];
  if (!original) throw new Error("Missing fixture app");
  mockData = [
    {
      ...original,
      actions: [
        ...original.actions,
        {
          action_id: "read",
          normalised_name: "Read messages",
          description: "",
          effective_policy: "ALWAYS",
          workspace_policy: "ASK",
          stored_policy: "ALWAYS",
          editable: true,
          lock_reason: null,
        },
      ],
    },
  ];
  render(<Form />);
  await user.click(
    screen.getByRole("switch", { name: "Enable Slack for this task" })
  );
  await user.click(screen.getByRole("button", { name: "Manage actions" }));
  await user.type(
    screen.getByRole("textbox", { name: "Search tools" }),
    "Send messages"
  );
  await user.click(screen.getByRole("combobox", { name: "Set permissions" }));
  await user.keyboard("{ArrowDown}{ArrowDown}{ArrowDown}{ArrowDown}{Enter}");
  expect(
    within(screen.getByRole("group", { name: "Send messages" })).getByRole(
      "button",
      { name: "Ask" }
    )
  ).toHaveAttribute("aria-pressed", "true");
  await user.click(screen.getByRole("button", { name: "Save changes" }));
  await user.click(screen.getByRole("button", { name: "Save task" }));
  expect(mockSave).toHaveBeenCalledWith([
    {
      gated_app_id: 1,
      enabled: true,
      action_policies: { send: "ASK", read: "ASK", delete: "DENY" },
    },
  ]);
});

it("explains workspace-disabled actions on hover without labeling personal choices as admin restrictions", async () => {
  const user = setupUser();
  render(<Form />);
  await user.click(
    screen.getByRole("switch", { name: "Enable Slack for this task" })
  );
  await user.click(screen.getByRole("button", { name: "Manage actions" }));
  await user.hover(screen.getByRole("group", { name: "Delete messages" }));
  expect(await screen.findByRole("tooltip")).toHaveTextContent(
    "An admin disabled this action for the workspace."
  );
  const send = screen.getByRole("group", { name: "Send messages" });
  await user.click(within(send).getByRole("button", { name: "Disabled" }));
  await user.hover(send);
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
});

it("explains admin-disabled actions in read-only task details", async () => {
  const user = setupUser();
  mockData = initialData.map((app) => ({ ...app, enabled: true }));
  render(<TaskActionPoliciesSummary taskId="task" />);
  await user.click(screen.getByRole("button", { name: "View actions" }));
  await user.hover(screen.getByRole("group", { name: "Delete messages" }));
  expect(await screen.findByRole("tooltip")).toHaveTextContent(
    "An admin disabled this action for the workspace."
  );
});

it("requires changes to save and confirms dirty cancel and escape", async () => {
  const user = setupUser();
  render(<Form />);
  await user.click(
    screen.getByRole("switch", { name: "Enable Slack for this task" })
  );
  await user.click(screen.getByRole("button", { name: "Manage actions" }));
  expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
  await user.click(
    within(screen.getByRole("group", { name: "Send messages" })).getByRole(
      "button",
      { name: "Ask" }
    )
  );
  expect(screen.getByRole("button", { name: "Save changes" })).toBeEnabled();
  await user.click(
    within(screen.getByRole("group", { name: "Send messages" })).getByRole(
      "button",
      { name: "Auto-approve" }
    )
  );
  expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
  await user.click(
    within(screen.getByRole("group", { name: "Send messages" })).getByRole(
      "button",
      { name: "Ask" }
    )
  );
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.getByText("Discard unsaved changes?")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.getByRole("button", { name: "Save changes" })).toBeEnabled();
  await user.keyboard("{Escape}");
  expect(screen.getByText("Discard unsaved changes?")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Discard changes" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(
    screen.getByText("1 auto-approve · 0 ask · 1 disabled")
  ).toBeInTheDocument();
});

it("waits for fresh policies before freezing a new task editor draft", async () => {
  const user = setupUser();
  mockIsValidating = true;
  const { rerender } = render(<Form taskId="task-id" />);
  expect(screen.getByRole("button", { name: "Save task" })).toBeDisabled();
  mockData = initialData.map((app) => ({
    ...app,
    enabled: true,
    actions: app.actions.map((action) => ({
      ...action,
      stored_policy: action.action_id === "send" ? "ASK" : null,
    })),
  }));
  mockIsValidating = false;
  rerender(<Form taskId="task-id" />);
  await user.click(screen.getByRole("button", { name: "Save task" }));
  expect(mockSave).toHaveBeenCalledWith([
    { gated_app_id: 1, enabled: true, action_policies: { send: "ASK" } },
  ]);
});

it.each([true, false])(
  "preserves saved empty ASK choices when enabled is %s",
  async (enabled) => {
    const user = setupUser();
    mockData = initialData.map((app) => ({
      ...app,
      enabled,
      actions: app.actions.map((action) => ({
        ...action,
        stored_policy: null,
        effective_policy: action.editable ? "ASK" : action.effective_policy,
      })),
    }));
    render(<Form taskId="task" />);
    const toggle = screen.getByRole("switch", {
      name: "Enable Slack for this task",
    });
    if (enabled) await user.click(toggle);
    await user.click(toggle);
    await user.click(screen.getByRole("button", { name: "Save task" }));
    expect(mockSave).toHaveBeenCalledWith([
      { gated_app_id: 1, enabled: true, action_policies: {} },
    ]);
  }
);
