import {
  render,
  screen,
  setupUser,
  waitFor,
  within,
  deferred,
} from "@tests/setup/test-utils";
import PersonalActionPoliciesModal from "@/app/craft/v1/apps/action-policies/PersonalActionPoliciesModal";
import type { AppActionPoliciesView } from "@/app/craft/v1/apps/action-policies/types";
jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn() }),
  usePathname: () => "/craft/v1/apps",
}));

const mockApp: AppActionPoliciesView = {
  gated_app_id: 2,
  kind: "mcp_server",
  target_id: 7,
  name: "Reports",
  users_can_manage_policies: true,
  enabled: null,
  actions: [
    {
      action_id: "send",
      normalised_name: "Send report",
      description: "",
      effective_policy: "ALWAYS",
      workspace_policy: "ASK",
      stored_policy: "ALWAYS",
      editable: true,
      lock_reason: null,
    },
  ],
};
const mockMutate = jest.fn();
let mockIsValidating = false;
jest.mock("swr", () => ({
  ...jest.requireActual("swr"),
  __esModule: true,
  default: (
    _key: string,
    _fetcher: unknown,
    options: { onSuccess: (app: AppActionPoliciesView) => void }
  ) => {
    const React = jest.requireActual<typeof import("react")>("react");
    React.useEffect(() => {
      if (!mockIsValidating) options.onSuccess(mockApp);
    }, [mockIsValidating, mockApp.actions, mockApp.users_can_manage_policies]);
    return {
      data: mockApp,
      mutate: mockMutate,
      isValidating: mockIsValidating,
    };
  },
}));
it("saves a personal MCP choice without requiring a credential flow", async () => {
  const user = setupUser();
  const close = jest.fn();
  const fetchMock = jest
    .spyOn(global, "fetch")
    .mockResolvedValue(new Response(null, { status: 200 }));
  render(
    <PersonalActionPoliciesModal
      kind="mcp_server"
      targetId={7}
      onClose={close}
    />
  );
  await user.click(
    within(screen.getByRole("group", { name: "Send report" })).getByRole(
      "button",
      { name: "Ask" }
    )
  );
  await user.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/build/action-policies/2",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({ action_policies: { send: "ASK" } }),
      })
    )
  );
  await waitFor(() => expect(close).toHaveBeenCalled());
  fetchMock.mockRestore();
});
it("reset saves an empty override map", async () => {
  const user = setupUser();
  const fetchMock = jest
    .spyOn(global, "fetch")
    .mockResolvedValue(new Response(null, { status: 200 }));
  render(
    <PersonalActionPoliciesModal
      kind="mcp_server"
      targetId={7}
      onClose={jest.fn()}
    />
  );
  await user.click(
    screen.getByRole("button", { name: "Reset all to workspace defaults" })
  );
  expect(fetchMock).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        body: JSON.stringify({ action_policies: {} }),
      })
    )
  );
  fetchMock.mockRestore();
});

it("saves the displayed default even if the workspace changes before save", async () => {
  const user = setupUser();
  const originalActions = mockApp.actions;
  const original = originalActions[0];
  if (!original) throw new Error("Missing fixture action");
  mockApp.actions = [
    { ...original, stored_policy: null, effective_policy: "ASK" },
    {
      ...original,
      action_id: "read",
      normalised_name: "Read report",
      stored_policy: "ASK",
      effective_policy: "ASK",
    },
  ];
  const fetchMock = jest
    .spyOn(global, "fetch")
    .mockResolvedValue(new Response(null, { status: 200 }));
  try {
    const { rerender } = render(
      <PersonalActionPoliciesModal
        kind="mcp_server"
        targetId={7}
        onClose={jest.fn()}
      />
    );
    mockApp.actions[0] = {
      ...original,
      stored_policy: null,
      effective_policy: "ALWAYS",
      workspace_policy: "ALWAYS",
    };
    rerender(
      <PersonalActionPoliciesModal
        kind="mcp_server"
        targetId={7}
        onClose={jest.fn()}
      />
    );
    await user.click(
      within(screen.getByRole("group", { name: "Read report" })).getByRole(
        "button",
        { name: "Auto-approve" }
      )
    );
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          body: JSON.stringify({
            action_policies: { send: "ASK", read: "ALWAYS" },
          }),
        })
      )
    );
  } finally {
    mockApp.actions = originalActions;
    fetchMock.mockRestore();
  }
});

it("applies bulk choices to the draft without changing locked actions", async () => {
  const user = setupUser();
  const originalActions = mockApp.actions;
  mockApp.actions = [
    ...originalActions,
    {
      action_id: "delete",
      normalised_name: "Delete report",
      description: "",
      effective_policy: "DENY",
      workspace_policy: "DENY",
      stored_policy: "ASK",
      editable: false,
      lock_reason: "workspace_disabled",
    },
  ];
  const fetchMock = jest
    .spyOn(global, "fetch")
    .mockResolvedValue(new Response(null, { status: 200 }));
  try {
    render(
      <PersonalActionPoliciesModal
        kind="mcp_server"
        targetId={7}
        onClose={jest.fn()}
      />
    );
    await user.type(
      screen.getByRole("textbox", { name: "Search actions" }),
      "Send report"
    );
    expect(screen.queryByText("Delete report")).not.toBeInTheDocument();
    const action = within(screen.getByRole("group", { name: "Send report" }));
    await user.click(screen.getAllByRole("button", { name: "Ask" })[0]!);
    expect(action.getByRole("button", { name: "Ask" })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
    await user.click(
      screen.getAllByRole("button", { name: "Auto-approve" })[0]!
    );
    expect(
      action.getByRole("button", { name: "Auto-approve" })
    ).toHaveAttribute("aria-pressed", "true");
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    await user.click(action.getByRole("button", { name: "Ask" }));
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          body: JSON.stringify({
            action_policies: { send: "ASK", delete: "ASK" },
          }),
        })
      )
    );
  } finally {
    mockApp.actions = originalActions;
    fetchMock.mockRestore();
  }
});

it("disables draft action edits while a personal save is pending", async () => {
  const user = setupUser();
  const pending = deferred<Response>();
  const close = jest.fn();
  const fetchMock = jest
    .spyOn(global, "fetch")
    .mockReturnValue(pending.promise);
  render(
    <PersonalActionPoliciesModal
      kind="mcp_server"
      targetId={7}
      onClose={close}
    />
  );
  await user.click(
    within(screen.getByRole("group", { name: "Send report" })).getByRole(
      "button",
      { name: "Ask" }
    )
  );
  await user.click(screen.getByRole("button", { name: "Save" }));
  for (const button of within(
    screen.getByRole("group", { name: "Send report" })
  ).getAllByRole("button")) {
    expect(button).toBeDisabled();
  }
  expect(
    screen.getByRole("button", { name: "Reset all to workspace defaults" })
  ).toBeDisabled();
  await user.keyboard("{Escape}");
  expect(close).not.toHaveBeenCalled();
  expect(
    screen.queryByText("Discard unsaved changes?")
  ).not.toBeInTheDocument();
  pending.resolve(new Response(null, { status: 200 }));
  await waitFor(() => expect(close).toHaveBeenCalled());
  fetchMock.mockRestore();
});

it("treats reset as a draft change and confirms dismissal without saving", async () => {
  const user = setupUser();
  const close = jest.fn();
  render(
    <PersonalActionPoliciesModal
      kind="mcp_server"
      targetId={7}
      onClose={close}
    />
  );
  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  await user.click(
    screen.getByRole("button", { name: "Reset all to workspace defaults" })
  );
  expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
  await user.keyboard("{Escape}");
  expect(screen.getByText("Discard unsaved changes?")).toBeInTheDocument();
  expect(close).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  await user.click(screen.getByRole("button", { name: "Discard changes" }));
  expect(close).toHaveBeenCalledTimes(1);
});

it("waits for fresh opening data and keeps later refreshes out of the draft", () => {
  const originalActions = mockApp.actions;
  mockIsValidating = true;
  try {
    const { rerender } = render(
      <PersonalActionPoliciesModal
        kind="mcp_server"
        targetId={7}
        onClose={jest.fn()}
      />
    );
    expect(
      screen.queryByRole("group", { name: "Send report" })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Retry" })
    ).not.toBeInTheDocument();
    mockApp.actions = originalActions.map((action) => ({
      ...action,
      effective_policy: "ASK",
      stored_policy: "ASK",
    }));
    mockIsValidating = false;
    rerender(
      <PersonalActionPoliciesModal
        kind="mcp_server"
        targetId={7}
        onClose={jest.fn()}
      />
    );
    expect(
      within(screen.getByRole("group", { name: "Send report" })).getByRole(
        "button",
        { name: "Ask" }
      )
    ).toHaveAttribute("aria-pressed", "true");
    mockApp.actions = originalActions;
    mockIsValidating = true;
    rerender(
      <PersonalActionPoliciesModal
        kind="mcp_server"
        targetId={7}
        onClose={jest.fn()}
      />
    );
    expect(
      within(screen.getByRole("group", { name: "Send report" })).getByRole(
        "button",
        { name: "Ask" }
      )
    ).toHaveAttribute("aria-pressed", "true");
  } finally {
    mockIsValidating = false;
    mockApp.actions = originalActions;
  }
});
