import { PointerEventsCheckLevel } from "@testing-library/user-event";
import { act } from "@testing-library/react";
import { useSWRConfig } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import IntegrationActionsTab from "@/sections/integrations/IntegrationActionsTab";
import messages from "@/i18n/messages/en.json";
import {
  makeAction,
  makeDetail,
  mockFetch,
  requestBody,
} from "@tests/setup/integrationTestUtils";

const copy = messages.admin.integrations.detail.actions;
const labels = messages.actions.policyToggle;
const URL_ACTIONS = "/api/admin/integrations/1/actions";

const actions = [
  makeAction(),
  makeAction({
    key: "get_issue",
    display_name: "Get issue",
    description: "Read one issue",
  }),
  makeAction({
    key: "create_issue",
    display_name: "Create issue",
    description: "Create an issue",
    read_only: false,
    default_policy: "ask",
    admin_policy: "blocked",
    effective_admin_policy: "blocked",
  }),
];

function user() {
  return setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
}

function rowOf(name: string): HTMLElement {
  const toggle = screen.getByRole("group", { name });
  const row = toggle.closest("div.flex.items-center.justify-between");
  if (!(row instanceof HTMLElement)) throw new Error(`No row for ${name}`);
  return row;
}

afterEach(() => jest.restoreAllMocks());

let revalidateActions: () => Promise<unknown> = async () => undefined;

/** Lets a test revalidate the actions, as a window focus does in the app. */
function ActionsRevalidator() {
  const { mutate } = useSWRConfig();
  revalidateActions = () => mutate(SWR_KEYS.adminIntegrationActions(1));
  return null;
}

test("groups actions with an unknown read-only state apart from write actions", async () => {
  mockFetch({
    [URL_ACTIONS]: {
      default_policy: null,
      actions: [
        ...actions,
        makeAction({
          key: "read_wiki",
          display_name: "Read wiki",
          read_only: null,
          default_policy: "ask",
        }),
      ],
    },
  });
  render(
    <IntegrationActionsTab
      integration={makeDetail()}
      onOpenConfiguration={jest.fn()}
    />
  );
  expect(
    await screen.findByText(copy.other.replace("{count}", "1"))
  ).toBeInTheDocument();
  expect(screen.getByText("Write Actions (1)")).toBeInTheDocument();
  expect(screen.getByText("Read-Only Actions (2)")).toBeInTheDocument();
});

test("shows the default row, then read-only and write actions with counts", async () => {
  mockFetch({ [URL_ACTIONS]: { default_policy: null, actions } });
  render(
    <IntegrationActionsTab
      integration={makeDetail()}
      onOpenConfiguration={jest.fn()}
    />
  );
  expect(await screen.findByText(copy.default.title)).toBeInTheDocument();
  expect(screen.getByText(copy.default.unset)).toBeInTheDocument();
  expect(screen.getByText("Read-Only Actions (2)")).toBeInTheDocument();
  expect(screen.getByText("Write Actions (1)")).toBeInTheDocument();
  expect(screen.getByText("2 actions")).toBeInTheDocument();
  expect(screen.getByText("1 action")).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Auto-approve" })
  ).not.toBeInTheDocument();

  const listIssues = within(rowOf("List issues"));
  expect(listIssues.getByText(copy.usesDefault)).toBeInTheDocument();
  expect(
    listIssues.getByRole("button", { name: labels.always.label })
  ).toHaveAttribute("aria-pressed", "true");

  const createIssue = within(rowOf("Create issue"));
  expect(createIssue.getByText(copy.setByAdmin)).toBeInTheDocument();
  expect(
    createIssue.getByRole("button", { name: labels.deny.label })
  ).toHaveAttribute("aria-pressed", "true");
});

test("saves only the default row and the actions that changed", async () => {
  const fetchMock = mockFetch({
    [URL_ACTIONS]: { default_policy: null, actions },
    [`PUT ${URL_ACTIONS}`]: { default_policy: "ask", actions },
  });
  const u = user();
  render(
    <IntegrationActionsTab
      integration={makeDetail()}
      onOpenConfiguration={jest.fn()}
    />
  );
  await screen.findByText(copy.default.title);
  expect(screen.getByRole("button", { name: copy.save })).toBeDisabled();

  const defaultRow = screen.getByRole("group", { name: copy.default.title });
  await u.click(
    within(defaultRow).getByRole("button", { name: labels.ask.label })
  );
  await u.click(
    within(rowOf("Get issue")).getByRole("button", { name: labels.ask.label })
  );
  expect(
    within(rowOf("Get issue")).getByText(copy.setByAdmin)
  ).toBeInTheDocument();
  // An action with no setting follows the new default.
  expect(
    within(rowOf("List issues")).getByRole("button", {
      name: labels.ask.label,
    })
  ).toHaveAttribute("aria-pressed", "true");

  await u.click(screen.getByRole("button", { name: copy.save }));
  await waitFor(() =>
    expect(requestBody(fetchMock, "PUT", URL_ACTIONS)).toEqual({
      default_policy: "ask",
      actions: { get_issue: "ask" },
    })
  );
});

test("a save after a revalidation keeps the newer values of rows it did not change", async () => {
  // Another admin blocked Get issue and allowed Create issue.
  const newerPolicy = { get_issue: "blocked", create_issue: "allow" } as const;
  const newer = actions.map((action) =>
    action.key === "get_issue" || action.key === "create_issue"
      ? {
          ...action,
          admin_policy: newerPolicy[action.key],
          effective_admin_policy: newerPolicy[action.key],
        }
      : action
  );
  let loads = 0;
  const fetchMock = mockFetch({
    [URL_ACTIONS]: () => {
      loads += 1;
      return { default_policy: null, actions: loads === 1 ? actions : newer };
    },
    [`PUT ${URL_ACTIONS}`]: { default_policy: "ask", actions: newer },
  });
  const u = user();
  render(
    <>
      <IntegrationActionsTab
        integration={makeDetail()}
        onOpenConfiguration={jest.fn()}
      />
      <ActionsRevalidator />
    </>
  );
  await screen.findByText(copy.default.title);
  const createIssue = () => within(rowOf("Create issue"));
  await u.click(createIssue().getByRole("button", { name: labels.ask.label }));
  await u.click(createIssue().getByRole("button", { name: labels.deny.label }));
  expect(screen.getByRole("button", { name: copy.save })).toBeDisabled();
  const defaultRow = screen.getByRole("group", { name: copy.default.title });
  await u.click(
    within(defaultRow).getByRole("button", { name: labels.ask.label })
  );

  await act(async () => {
    await revalidateActions();
  });
  await waitFor(() =>
    expect(
      createIssue().getByRole("button", { name: labels.always.label })
    ).toHaveAttribute("aria-pressed", "true")
  );
  expect(
    within(rowOf("Get issue")).getByRole("button", { name: labels.deny.label })
  ).toHaveAttribute("aria-pressed", "true");

  await u.click(screen.getByRole("button", { name: copy.save }));
  await waitFor(() =>
    expect(requestBody(fetchMock, "PUT", URL_ACTIONS)).toEqual({
      default_policy: "ask",
      actions: {},
    })
  );
});

test("an edit that a revalidation saved does not cover a later value", async () => {
  const withCreateIssue = (policy: "ask" | "allow") =>
    actions.map((action) =>
      action.key === "create_issue"
        ? { ...action, admin_policy: policy, effective_admin_policy: policy }
        : action
    );
  let loads = 0;
  mockFetch({
    [URL_ACTIONS]: () => {
      loads += 1;
      const policy = loads === 2 ? "ask" : "allow";
      return {
        default_policy: null,
        actions: loads === 1 ? actions : withCreateIssue(policy),
      };
    },
  });
  const u = user();
  render(
    <>
      <IntegrationActionsTab
        integration={makeDetail()}
        onOpenConfiguration={jest.fn()}
      />
      <ActionsRevalidator />
    </>
  );
  await screen.findByText(copy.default.title);
  const createIssue = () => within(rowOf("Create issue"));
  await u.click(createIssue().getByRole("button", { name: labels.ask.label }));

  for (let round = 0; round < 2; round++) {
    await act(async () => {
      await revalidateActions();
    });
  }
  await waitFor(() =>
    expect(
      createIssue().getByRole("button", { name: labels.always.label })
    ).toHaveAttribute("aria-pressed", "true")
  );
  expect(screen.getByRole("button", { name: copy.save })).toBeDisabled();
});

test("Use defaults clears the admin values of a group", async () => {
  const fetchMock = mockFetch({
    [URL_ACTIONS]: { default_policy: "allow", actions },
    [`PUT ${URL_ACTIONS}`]: { default_policy: "allow", actions },
  });
  const u = user();
  render(
    <IntegrationActionsTab
      integration={makeDetail()}
      onOpenConfiguration={jest.fn()}
    />
  );
  await screen.findByText("Write Actions (1)");
  const selects = screen.getAllByRole("combobox");
  await u.click(selects[selects.length - 1] as HTMLElement);
  await u.click(await screen.findByRole("option", { name: copy.useDefaults }));
  expect(
    within(rowOf("Create issue")).getByText(copy.usesDefault)
  ).toBeInTheDocument();
  await u.click(screen.getByRole("button", { name: copy.save }));
  await waitFor(() =>
    expect(requestBody(fetchMock, "PUT", URL_ACTIONS)).toEqual({
      actions: { create_issue: null },
    })
  );
});

test("refreshes the actions of an MCP server", async () => {
  const fetchMock = mockFetch({
    [URL_ACTIONS]: { default_policy: null, actions: [] },
    [`POST ${URL_ACTIONS}/refresh`]: { default_policy: null, actions },
  });
  const u = user();
  render(
    <IntegrationActionsTab
      integration={makeDetail({ auth_mode: "none", auth_method: null })}
      onOpenConfiguration={jest.fn()}
    />
  );
  expect(await screen.findByText(copy.empty)).toBeInTheDocument();
  await u.click(screen.getByRole("button", { name: copy.refresh }));
  expect(await screen.findByText("Read-Only Actions (2)")).toBeInTheDocument();
  expect(
    fetchMock.mock.calls.some(
      ([input, init]) =>
        String(input) === `${URL_ACTIONS}/refresh` && init?.method === "POST"
    )
  ).toBe(true);
});

test("blocks Refresh while the action settings have unsaved changes", async () => {
  mockFetch({ [URL_ACTIONS]: { default_policy: null, actions } });
  const u = user();
  render(
    <IntegrationActionsTab
      integration={makeDetail({ auth_mode: "none", auth_method: null })}
      onOpenConfiguration={jest.fn()}
    />
  );
  const refresh = await screen.findByRole("button", { name: copy.refresh });
  expect(refresh).toBeEnabled();
  await u.click(
    within(rowOf("List issues")).getByRole("button", {
      name: labels.deny.label,
    })
  );
  expect(refresh).toBeDisabled();
});

test("asks to connect an MCP server before its actions load", async () => {
  mockFetch({ [URL_ACTIONS]: { default_policy: null, actions: [] } });
  const onOpenConfiguration = jest.fn();
  const u = user();
  render(
    <IntegrationActionsTab
      integration={makeDetail({
        auth_mode: "shared",
        organization_status: {
          state: "not_set_up",
          reason: null,
        },
      })}
      onOpenConfiguration={onOpenConfiguration}
    />
  );
  expect(await screen.findByText(copy.connectFirst.title)).toBeInTheDocument();
  await u.click(screen.getByRole("button", { name: copy.connectFirst.open }));
  expect(onOpenConfiguration).toHaveBeenCalled();
});

test("has no Refresh button for an app and no edits without manage access", async () => {
  mockFetch({ [URL_ACTIONS]: { default_policy: null, actions } });
  render(
    <IntegrationActionsTab
      integration={makeDetail({
        shape: "openapi",
        kind: "api",
        can_manage: false,
      })}
      onOpenConfiguration={jest.fn()}
    />
  );
  await screen.findByText("Write Actions (1)");
  expect(
    screen.queryByRole("button", { name: copy.refresh })
  ).not.toBeInTheDocument();
  expect(
    within(rowOf("Create issue")).getByRole("button", {
      name: labels.ask.label,
    })
  ).toBeDisabled();
  expect(
    within(rowOf("Create issue")).getByRole("button", {
      name: labels.deny.label,
    })
  ).toHaveAttribute("aria-pressed", "true");
});

test("tells the admin to connect an own account for an individual MCP server", async () => {
  mockFetch({ [URL_ACTIONS]: { default_policy: null, actions: [] } });
  render(
    <IntegrationActionsTab
      integration={makeDetail({ auth_mode: "individual" })}
      onOpenConfiguration={jest.fn()}
    />
  );
  expect(
    await screen.findByText(copy.connectFirst.individualDescription)
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: copy.connectFirst.open })
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: copy.connectFirst.openIntegration })
  ).toBeInTheDocument();
});

test("locks Allow for an action that Craft always asks for, with the reason", async () => {
  const fetchMock = mockFetch({
    [URL_ACTIONS]: {
      default_policy: "allow",
      actions: [
        makeAction({ read_only: false }),
        makeAction({
          key: "unspecified",
          display_name: "Other requests",
          description: "Requests that match no other action",
          read_only: false,
          default_policy: "ask",
          effective_admin_policy: "ask",
          always_asks: true,
        }),
      ],
    },
    [`PUT ${URL_ACTIONS}`]: { default_policy: "allow", actions: [] },
  });
  const u = user();
  render(
    <IntegrationActionsTab
      integration={makeDetail({ kind: "api", shape: "custom" })}
      onOpenConfiguration={jest.fn()}
    />
  );
  const other = within(await waitFor(() => rowOf("Other requests")));
  expect(other.getByText(copy.alwaysAsks)).toBeInTheDocument();
  expect(
    other.getByRole("button", { name: labels.always.label })
  ).toBeDisabled();
  expect(other.getByRole("button", { name: labels.ask.label })).toHaveAttribute(
    "aria-pressed",
    "true"
  );
  expect(other.getByRole("button", { name: labels.deny.label })).toBeEnabled();

  // Allow for the whole group skips the locked action.
  await u.click(
    screen.getByRole("combobox", {
      name: messages.craft.actionPolicies.setPermissions,
    })
  );
  await u.click(
    await screen.findByRole("option", { name: labels.always.label })
  );
  await u.click(screen.getByRole("button", { name: copy.save }));
  await waitFor(() =>
    expect(requestBody(fetchMock, "PUT", URL_ACTIONS)).toEqual({
      actions: { list_issues: "allow" },
    })
  );
});
