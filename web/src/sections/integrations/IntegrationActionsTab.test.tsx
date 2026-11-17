import { PointerEventsCheckLevel } from "@testing-library/user-event";
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
} from "@/sections/integrations/__tests__/integrationFixtures";

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

test("saves the default row and each changed action", async () => {
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
      actions: {
        list_issues: null,
        get_issue: "ask",
        create_issue: "blocked",
      },
    })
  );
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
      default_policy: "allow",
      actions: { list_issues: null, get_issue: null, create_issue: null },
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
