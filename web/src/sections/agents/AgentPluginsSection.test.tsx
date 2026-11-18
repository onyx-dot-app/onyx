import { useState } from "react";
import { PointerEventsCheckLevel } from "@testing-library/user-event";
import { render, screen, setupUser, within } from "@tests/setup/test-utils";
import AgentPluginsSection from "@/sections/agents/AgentPluginsSection";
import type { AgentPluginDraft } from "@/lib/agents/plugins";
import type {
  AgentCatalogIntegration,
  AgentPluginOption,
} from "@/lib/integrations/types";
import messages from "@/i18n/messages/en.json";
import { makeAction, mockFetch } from "@tests/setup/integrationTestUtils";

let mockManage = false;
jest.mock("@/lib/permissions/hooks", () => ({
  usePermissionAuthority: () => ({
    isGlobalHolder: mockManage,
    isScopedManager: false,
  }),
}));

Element.prototype.scrollIntoView = jest.fn();

const copy = messages.agents.editor.plugins;
const CATALOG = "/api/integrations/agent-catalog";

function linear(
  overrides: Partial<AgentCatalogIntegration> = {}
): AgentCatalogIntegration {
  return {
    id: 7,
    name: "Linear",
    kind: "mcp",
    shape: "mcp_server",
    users_can_save_always_allow: true,
    actions: [
      makeAction(),
      makeAction({
        key: "create_issue",
        display_name: "Create issue",
        description: "Create an issue",
        read_only: false,
        default_policy: "ask",
        effective_admin_policy: "ask",
      }),
      makeAction({
        key: "delete_issue",
        display_name: "Delete issue",
        description: "Delete an issue",
        read_only: false,
        default_policy: "ask",
        admin_policy: "blocked",
        effective_admin_policy: "blocked",
      }),
    ],
    ...overrides,
  };
}

function plugin(overrides: Partial<AgentPluginOption> = {}): AgentPluginOption {
  return {
    plugin_id: "plugin-linear",
    plugin_name: "Linear plugin",
    description: "Issues and projects",
    integrations: [linear()],
    ...overrides,
  };
}

const jira = plugin({
  plugin_id: "plugin-jira",
  plugin_name: "Jira plugin",
  description: null,
  integrations: [],
});

function draft(overrides: Partial<AgentPluginDraft> = {}): AgentPluginDraft {
  return {
    plugin_id: "plugin-linear",
    plugin_name: "Linear plugin",
    default: "inherit",
    actions: {},
    ...overrides,
  };
}

interface HarnessProps {
  initial: AgentPluginDraft[];
  onChange: (value: AgentPluginDraft[]) => void;
}

function Harness({ initial, onChange }: HarnessProps) {
  const [value, setValue] = useState(initial);
  return (
    <AgentPluginsSection
      value={value}
      onChange={(next) => {
        setValue(next);
        onChange(next);
      }}
    />
  );
}

function setup(
  initial: AgentPluginDraft[],
  catalog: AgentPluginOption[] = [plugin(), jira]
) {
  mockFetch({ [CATALOG]: catalog });
  const onChange = jest.fn();
  render(<Harness initial={initial} onChange={onChange} />);
  return onChange;
}

function user() {
  return setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
}

function select(name: string): HTMLElement {
  return screen.getByRole("combobox", { name });
}

async function optionsOf(name: string): Promise<string[]> {
  await user().click(select(name));
  const listbox = await screen.findByRole("listbox");
  const titles = within(listbox)
    .getAllByRole("option")
    .map((option) => option.textContent ?? "");
  await user().keyboard("{Escape}");
  return titles;
}

async function pick(name: string, option: string) {
  const u = user();
  await u.click(select(name));
  await u.click(await screen.findByRole("option", { name: option }));
}

afterEach(() => {
  jest.restoreAllMocks();
  mockManage = false;
});

// ── Catalog, add and remove ──────────────────────────────────────────────────

test("adds a plugin from the catalog with every action inherited", async () => {
  const onChange = setup([]);
  await screen.findByRole("combobox", { name: copy.add.placeholder });
  await pick(copy.add.placeholder, "Linear plugin");

  expect(onChange).toHaveBeenLastCalledWith([draft()]);
  expect(await screen.findByText("Issues and projects")).toBeInTheDocument();
  expect(screen.getByText("List issues")).toBeInTheDocument();
  expect(screen.getByText("Create issue")).toBeInTheDocument();
  expect(await optionsOf(copy.add.placeholder)).toEqual(["Jira plugin"]);
});

test("removes a plugin", async () => {
  const onChange = setup([draft()]);
  await user().click(
    await screen.findByRole("button", { name: "Remove Linear plugin" })
  );
  expect(onChange).toHaveBeenLastCalledWith([]);
  expect(screen.queryByText("List issues")).not.toBeInTheDocument();
});

test("keeps a plugin the user cannot see, with its settings", async () => {
  const onChange = setup(
    [draft({ plugin_id: "hidden", plugin_name: "Hidden plugin" })],
    [jira]
  );
  expect(await screen.findByText("Hidden plugin")).toBeInTheDocument();
  expect(screen.getByText(copy.notVisible)).toBeInTheDocument();
  expect(onChange).not.toHaveBeenCalled();
});

test("says when no plugin holds an integration", async () => {
  setup([], []);
  expect(await screen.findByText(copy.empty)).toBeInTheDocument();
});

// ── Choices ──────────────────────────────────────────────────────────────────

test("offers the agent default and four choices, with no Auto, and sets each action", async () => {
  const onChange = setup([draft()]);
  const createIssue = "Setting for Create issue";
  await screen.findByRole("combobox", { name: createIssue });
  expect(await optionsOf(createIssue)).toEqual([
    copy.choice.agentDefault,
    copy.choice.inherit,
    "Allow",
    "Ask",
    "Blocked",
  ]);

  await pick(createIssue, "Blocked");
  expect(onChange).toHaveBeenLastCalledWith([
    draft({ actions: { create_issue: "blocked" } }),
  ]);
  await pick(createIssue, "Allow");
  expect(onChange).toHaveBeenLastCalledWith([
    draft({ actions: { create_issue: "allow" } }),
  ]);
  await pick(createIssue, "Ask");
  expect(onChange).toHaveBeenLastCalledWith([
    draft({ actions: { create_issue: "ask" } }),
  ]);
  await pick(createIssue, copy.choice.inherit);
  expect(onChange).toHaveBeenLastCalledWith([
    draft({ actions: { create_issue: "inherit" } }),
  ]);
  await pick(createIssue, copy.choice.agentDefault);
  expect(onChange).toHaveBeenLastCalledWith([draft()]);
});

test("shows a migrated inherit action as the integration setting under a blocked default", async () => {
  setup([draft({ default: "blocked", actions: { list_issues: "inherit" } })]);
  expect(
    await screen.findByRole("combobox", { name: "Setting for List issues" })
  ).toHaveValue(copy.choice.inherit);
  expect(screen.getByText("Allows (integration setting)")).toBeInTheDocument();
  expect(
    screen.getByRole("combobox", { name: "Setting for Create issue" })
  ).toHaveValue(copy.choice.agentDefault);
});

test("shows the stricter setting of another plugin that holds the integration", async () => {
  const other = plugin({
    plugin_id: "plugin-other",
    plugin_name: "Other plugin",
  });
  setup(
    [
      draft(),
      draft({
        plugin_id: "plugin-other",
        plugin_name: "Other plugin",
        actions: { list_issues: "blocked" },
      }),
    ],
    [plugin(), other]
  );
  expect(
    await screen.findByText(
      copy.stricterPlugin.replace("{plugin}", "Other plugin")
    )
  ).toBeInTheDocument();
});

test("sets the default for other actions", async () => {
  const onChange = setup([draft()]);
  const defaultRow = "Default setting for Linear plugin";
  await screen.findByRole("combobox", { name: defaultRow });
  expect(await optionsOf(defaultRow)).toEqual([
    copy.choice.inherit,
    "Allow",
    "Ask",
    "Blocked",
  ]);
  await pick(defaultRow, "Ask");
  expect(onChange).toHaveBeenLastCalledWith([draft({ default: "ask" })]);
  expect(screen.getAllByText("Asks (agent default)")).toHaveLength(2);
});

// ── Lock rules ───────────────────────────────────────────────────────────────

test("does not offer Allow on an action the admin blocked", async () => {
  setup([draft()]);
  const deleteIssue = "Setting for Delete issue";
  await screen.findByRole("combobox", { name: deleteIssue });
  expect(await optionsOf(deleteIssue)).toEqual([
    copy.choice.agentDefault,
    copy.choice.inherit,
    "Ask",
    "Blocked",
  ]);
  expect(screen.getByText(copy.lock.adminBlocked)).toBeInTheDocument();
});

test("does not offer Allow when users cannot save Always allow", async () => {
  setup(
    [draft()],
    [plugin({ integrations: [linear({ users_can_save_always_allow: false })] })]
  );
  const createIssue = "Setting for Create issue";
  await screen.findByRole("combobox", { name: createIssue });
  expect(await optionsOf(createIssue)).not.toContain("Allow");
  expect(await optionsOf("Default setting for Linear plugin")).not.toContain(
    "Allow"
  );
  expect(screen.getAllByText(copy.lock.adminFinal)).toHaveLength(2);
  expect(screen.getByText(copy.lock.defaultFinal)).toBeInTheDocument();
  expect(screen.getAllByText(copy.askHintAdminOnly)).toHaveLength(1);
});

test("does not offer Allow on an action that always asks", async () => {
  setup(
    [draft()],
    [
      plugin({
        integrations: [
          linear({
            kind: "api",
            shape: "custom",
            actions: [
              makeAction({
                key: "unspecified",
                display_name: "Any request",
                default_policy: "ask",
                effective_admin_policy: "ask",
                always_asks: true,
              }),
            ],
          }),
        ],
      }),
    ]
  );
  const anyRequest = "Setting for Any request";
  await screen.findByRole("combobox", { name: anyRequest });
  expect(await optionsOf(anyRequest)).not.toContain("Allow");
  expect(screen.getByText(copy.lock.alwaysAsks)).toBeInTheDocument();
  expect(screen.queryByText(copy.askHint)).not.toBeInTheDocument();
});

test("keeps showing a migrated Allow on a locked action and lets the owner change it", async () => {
  const onChange = setup([draft({ actions: { delete_issue: "allow" } })]);
  const deleteIssue = "Setting for Delete issue";
  expect(
    await screen.findByRole("combobox", { name: deleteIssue })
  ).toHaveValue("Allow");
  expect(screen.getByText("Blocked (integration setting)")).toBeInTheDocument();
  await pick(deleteIssue, "Blocked");
  expect(onChange).toHaveBeenLastCalledWith([
    draft({ actions: { delete_issue: "blocked" } }),
  ]);
  expect(await optionsOf(deleteIssue)).not.toContain("Allow");
});

// ── Effective setting ────────────────────────────────────────────────────────

test("tells the owner to change an agent Ask that the integration allows", async () => {
  mockManage = true;
  setup([draft({ actions: { list_issues: "ask" } })]);
  expect(await screen.findByText("Asks (agent setting)")).toBeInTheDocument();
  expect(screen.getAllByText(copy.askHintAgent)).toHaveLength(1);
  expect(screen.getAllByText(copy.askHint)).toHaveLength(1);
  // Only the Ask of the integration links to its Actions tab.
  expect(
    screen.getAllByRole("link", { name: "Open Linear actions" })
  ).toHaveLength(1);
});

test("names the agent setting in the hint for an integration Ask that the agent can allow", async () => {
  setup([draft()]);
  const createIssue = "Setting for Create issue";
  await screen.findByRole("combobox", { name: createIssue });
  expect(await optionsOf(createIssue)).toContain("Allow");
  expect(screen.getByText(copy.askHint)).toHaveTextContent(
    /change the agent setting/
  );
});

test("leaves out Always allow from the agent hint when users cannot save it", async () => {
  setup(
    [draft({ actions: { list_issues: "ask" } })],
    [plugin({ integrations: [linear({ users_can_save_always_allow: false })] })]
  );
  expect(await screen.findByText("Asks (agent setting)")).toBeInTheDocument();
  expect(screen.getAllByText(copy.askHintAgentOnly)).toHaveLength(1);
});

test("links an admin to the Actions tab of the integration", async () => {
  mockManage = true;
  setup([draft()]);
  expect(
    await screen.findByRole("link", { name: "Open Linear actions" })
  ).toHaveAttribute("href", "/admin/integrations/7?tab=actions");
});
