import {
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import MCPServerToolsEditor from "@/sections/actions/MCPServerToolsEditor";
import { MCPServerStatus, type MCPServer } from "@/lib/mcp/types";
import type { ToolSnapshot } from "@/lib/tools/types";
import { refreshMCPServerTools, updateMCPServer } from "@/lib/mcp/svc";
import { updateToolsStatus } from "@/lib/tools/svc";
import { useSettings } from "@/lib/settings/hooks";
import messages from "@/i18n/messages/en.json";

jest.mock("@/lib/mcp/svc", () => ({
  refreshMCPServerTools: jest.fn(),
  updateMCPServer: jest.fn(),
}));
jest.mock("@/lib/tools/svc", () => ({ updateToolsStatus: jest.fn() }));
jest.mock("@/lib/settings/hooks", () => ({ useSettings: jest.fn() }));
const server: MCPServer = {
  connection_status: null,
  id: 7,
  name: "Example",
  server_url: "https://example.com/mcp",
  owner: "admin",
  status: MCPServerStatus.CONNECTED,
  is_public: true,
  groups: [],
  users: [],
  tool_count: 2,
  users_can_manage_policies: true,
  action_policies: { disabled_tool: "DENY" },
  permissions: { edit: true, manage_status: true },
};
const tool: ToolSnapshot = {
  id: 1,
  name: "raw_tool",
  display_name: "Display tool",
  description: "Reads records",
  definition: null,
  custom_headers: [],
  in_code_tool_id: null,
  passthrough_auth: false,
  enabled: true,
  chat_selectable: true,
  agent_creation_selectable: true,
  default_enabled: true,
  permissions: { toggle: true },
};
let snapshots: ToolSnapshot[];
const dirty = jest.fn();
const busy = jest.fn();
const saved = jest.fn<Promise<void>, []>();
function Harness({ value = server }: { value?: MCPServer }) {
  return (
    <MCPServerToolsEditor
      server={value}
      onDirtyChange={dirty}
      onBusyChange={busy}
      onSaved={saved}
    />
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  jest
    .mocked(useSettings)
    .mockReturnValue({ onyx_craft_available: true } as ReturnType<
      typeof useSettings
    >);
  snapshots = [
    tool,
    {
      ...tool,
      id: 2,
      name: "disabled_tool",
      display_name: "Disabled tool",
      enabled: false,
    },
  ];
  global.fetch = jest
    .fn()
    .mockImplementation(async () => new Response(JSON.stringify(snapshots)));
  jest
    .mocked(updateToolsStatus)
    .mockResolvedValue({ updated_count: 1, tool_ids: [1] });
  jest.mocked(updateMCPServer).mockResolvedValue(server);
  jest.mocked(refreshMCPServerTools).mockResolvedValue(snapshots);
  saved.mockResolvedValue();
});
it("keeps descriptions visible when an admin changes tool availability", async () => {
  const user = setupUser();
  render(<Harness />);
  const toggle = await screen.findByRole("switch", {
    name: "tool-toggle-Display tool",
  });
  expect(screen.getAllByText("Reads records")[0]).toBeVisible();
  await user.click(toggle);
  expect(screen.getAllByText("Reads records")[0]).toBeVisible();
  expect(
    screen.queryByRole("button", { name: /Expand/ })
  ).not.toBeInTheDocument();
});

it("keeps enablement as a draft, then saves and resets dirty state", async () => {
  const user = setupUser();
  render(<Harness />);
  await user.click(
    await screen.findByRole("switch", { name: "tool-toggle-Display tool" })
  );
  expect(updateToolsStatus).not.toHaveBeenCalled();
  await waitFor(() => expect(dirty).toHaveBeenLastCalledWith(true));
  await user.click(
    screen.getByRole("button", {
      name: messages.actions.addMcpModal.submitButton.saveLabel,
    })
  );
  await waitFor(() =>
    expect(updateToolsStatus).toHaveBeenCalledWith([1], false)
  );
  await waitFor(() => expect(dirty).toHaveBeenLastCalledWith(false));
  expect(saved).toHaveBeenCalledTimes(1);
});
it("uses raw names for Craft policies and preserves disabled-tool overrides", async () => {
  const user = setupUser();
  render(<Harness />);
  await screen.findByRole("switch", { name: "tool-toggle-Display tool" });
  await user.click(
    screen.getByRole("tab", { name: messages.actions.mcpTools.policiesTab })
  );
  await user.click(
    screen.getByRole("combobox", {
      name: messages.craft.apps.policyEditor.permissions.title,
    })
  );
  await user.click(
    await screen.findByRole("option", {
      name: messages.craft.apps.policyEditor.permissions.autoApproveOption,
    })
  );
  await user.click(
    screen.getByRole("button", {
      name: messages.actions.addMcpModal.submitButton.saveLabel,
    })
  );
  await waitFor(() =>
    expect(updateMCPServer).toHaveBeenCalledWith(7, {
      action_policies: { raw_tool: "ALWAYS", disabled_tool: "DENY" },
    })
  );
});
it("keeps the same list viewport when switching availability and Craft permissions", async () => {
  render(<Harness />);
  await screen.findByRole("switch", { name: "tool-toggle-Display tool" });
  const viewport = screen.getByRole("region", { name: "Tools" });
  expect(within(viewport).getAllByRole("listitem")).toHaveLength(2);
  const user = setupUser();
  await user.click(
    screen.getByRole("tab", { name: messages.actions.mcpTools.policiesTab })
  );
  expect(screen.getByRole("region", { name: "Tools" })).toBe(viewport);
  expect(within(viewport).getAllByRole("listitem")).toHaveLength(1);
  expect(
    screen.queryByRole("switch", {
      name: messages.actions.toolsList.showEnabledButton.ariaLabel,
    })
  ).not.toBeInTheDocument();
  await user.click(
    screen.getByRole("tab", { name: messages.actions.mcpTools.enabledTab })
  );
  expect(screen.getByRole("region", { name: "Tools" })).toBe(viewport);
  expect(within(viewport).getAllByRole("listitem")).toHaveLength(2);
});

it("hides Craft policies without Craft and respects tool permissions", async () => {
  jest
    .mocked(useSettings)
    .mockReturnValue({ onyx_craft_available: false } as ReturnType<
      typeof useSettings
    >);
  snapshots = [{ ...tool, permissions: {} }];
  render(<Harness value={{ ...server, permissions: {} }} />);
  expect(
    await screen.findByRole("switch", { name: "tool-toggle-Display tool" })
  ).toHaveAttribute("aria-disabled", "true");
  expect(
    screen.queryByRole("tab", { name: messages.actions.mcpTools.policiesTab })
  ).not.toBeInTheDocument();
  expect(screen.queryByRole("tab")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: messages.actions.mcpTools.refresh })
  ).not.toBeInTheDocument();
});
it("retains failed changes for retry after a partial batch save", async () => {
  snapshots = [
    { ...tool, enabled: true },
    { ...tool, id: 2, name: "other", display_name: "Other", enabled: false },
  ];
  jest
    .mocked(updateToolsStatus)
    .mockResolvedValueOnce({ updated_count: 1, tool_ids: [1] })
    .mockRejectedValueOnce(new Error("Enable failed"));
  const user = setupUser();
  render(<Harness />);
  await user.click(
    await screen.findByRole("switch", { name: "tool-toggle-Display tool" })
  );
  await user.click(screen.getByRole("switch", { name: "tool-toggle-Other" }));
  await user.click(
    screen.getByRole("button", {
      name: messages.actions.addMcpModal.submitButton.saveLabel,
    })
  );
  await screen.findByText("Enable failed");
  expect(dirty).toHaveBeenLastCalledWith(true);
  await user.click(
    screen.getByRole("button", {
      name: messages.actions.addMcpModal.submitButton.saveLabel,
    })
  );
  await waitFor(() => expect(updateToolsStatus).toHaveBeenCalledTimes(3));
  expect(jest.mocked(updateToolsStatus).mock.calls).toEqual([
    [[1], false],
    [[2], true],
    [[2], true],
  ]);
});
it("refreshes tools and blocks refresh while draft changes exist", async () => {
  const user = setupUser();
  render(<Harness />);
  await user.click(
    await screen.findByRole("button", {
      name: messages.actions.mcpTools.refresh,
    })
  );
  await waitFor(() => expect(refreshMCPServerTools).toHaveBeenCalledWith(7));
  await user.click(
    await screen.findByRole("switch", { name: "tool-toggle-Display tool" })
  );
  expect(
    screen.getByRole("button", { name: messages.actions.mcpTools.refresh })
  ).toBeDisabled();
});

it("treats mixed permissions as valid and excludes removed tools from saves", async () => {
  const user = setupUser();
  render(
    <Harness
      value={{
        ...server,
        action_policies: { raw_tool: "DENY", removed_tool: "ALWAYS" },
      }}
    />
  );
  await screen.findByRole("switch", { name: "tool-toggle-Display tool" });
  await user.click(
    screen.getByRole("tab", { name: messages.actions.mcpTools.policiesTab })
  );
  expect(
    screen.queryByText("Please select a valid option from the list")
  ).not.toBeInTheDocument();
  await user.click(
    screen.getByRole("combobox", {
      name: messages.craft.apps.policyEditor.permissions.title,
    })
  );
  await user.click(
    await screen.findByRole("option", {
      name: messages.craft.apps.policyEditor.permissions.autoApproveOption,
    })
  );
  await user.click(
    screen.getByRole("button", {
      name: messages.actions.addMcpModal.submitButton.saveLabel,
    })
  );
  await waitFor(() =>
    expect(updateMCPServer).toHaveBeenCalledWith(7, {
      action_policies: { raw_tool: "ALWAYS" },
    })
  );
});

it("renders its save controls inline without a dialog or footer portal", async () => {
  const { container } = render(<Harness />);
  await screen.findByRole("switch", { name: "tool-toggle-Display tool" });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(container).toContainElement(
    screen.getByRole("button", {
      name: messages.actions.addMcpModal.submitButton.saveLabel,
    })
  );
  expect(
    screen.getByRole("button", {
      name: messages.actions.addMcpModal.submitButton.saveLabel,
    })
  ).toBeDisabled();
});

it("reports pending saves and locks editing until the request completes", async () => {
  let completeSave: (() => void) | undefined;
  jest.mocked(updateToolsStatus).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        completeSave = () => resolve({ updated_count: 1, tool_ids: [1] });
      })
  );
  const user = setupUser();
  render(<Harness />);
  const toggle = await screen.findByRole("switch", {
    name: "tool-toggle-Display tool",
  });
  await user.click(toggle);
  await user.click(
    screen.getByRole("button", {
      name: messages.actions.addMcpModal.submitButton.saveLabel,
    })
  );
  await waitFor(() => expect(busy).toHaveBeenLastCalledWith(true));
  expect(toggle).toBeDisabled();
  expect(
    screen.getByRole("button", { name: messages.actions.mcpTools.refresh })
  ).toBeDisabled();
  completeSave?.();
  await waitFor(() => expect(busy).toHaveBeenLastCalledWith(false));
  expect(toggle).toBeEnabled();
  expect(dirty).toHaveBeenLastCalledWith(false);
});

it("disables duplicate tool discovery while the server is fetching", async () => {
  render(
    <Harness value={{ ...server, status: MCPServerStatus.FETCHING_TOOLS }} />
  );
  await screen.findByRole("switch", { name: "tool-toggle-Display tool" });
  expect(
    screen.getByRole("button", { name: messages.actions.mcpTools.refresh })
  ).toBeDisabled();
});

it("shows disabled tools and applies explicit bulk actions only to the draft", async () => {
  const user = setupUser();
  render(<Harness />);
  await screen.findByRole("switch", { name: "tool-toggle-Display tool" });
  expect(
    screen.queryByRole("switch", {
      name: messages.actions.toolsList.showEnabledButton.ariaLabel,
    })
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("switch", { name: "tool-toggle-Disabled tool" })
  ).not.toBeChecked();
  await user.click(
    screen.getByRole("button", {
      name: messages.actions.toolsList.enableAllButton.label,
    })
  );
  expect(
    await screen.findByRole("switch", { name: "tool-toggle-Disabled tool" })
  ).toBeChecked();
  expect(updateToolsStatus).not.toHaveBeenCalled();
  await user.type(
    screen.getByRole("textbox", { name: messages.actions.mcpTools.search }),
    "missing"
  );
  expect(
    screen.getByText(messages.actions.toolsList.empty.searchMessage)
  ).toBeVisible();
  await user.clear(
    screen.getByRole("textbox", { name: messages.actions.mcpTools.search })
  );
  await user.click(
    screen.getByRole("button", {
      name: messages.actions.toolsList.disableAllButton.ariaLabel,
    })
  );
  expect(
    screen.getByRole("switch", { name: "tool-toggle-Display tool" })
  ).not.toBeChecked();
  expect(
    screen.getByRole("switch", { name: "tool-toggle-Disabled tool" })
  ).not.toBeChecked();
  expect(updateToolsStatus).not.toHaveBeenCalled();
});

it("searches policy rows while bulk policy changes include hidden enabled tools", async () => {
  snapshots.push({
    ...tool,
    id: 3,
    name: "hidden_tool",
    display_name: "Hidden tool",
  });
  const user = setupUser();
  render(<Harness />);
  await screen.findByRole("switch", { name: "tool-toggle-Display tool" });
  await user.click(
    screen.getByRole("tab", { name: messages.actions.mcpTools.policiesTab })
  );
  expect(screen.getAllByRole("listitem")).toHaveLength(2);
  await user.type(
    screen.getByRole("textbox", { name: messages.actions.mcpTools.search }),
    "Display"
  );
  expect(screen.getAllByRole("listitem")).toHaveLength(1);
  await user.click(
    screen.getByRole("combobox", {
      name: messages.craft.apps.policyEditor.permissions.title,
    })
  );
  await user.click(
    await screen.findByRole("option", {
      name: messages.craft.apps.policyEditor.permissions.autoApproveOption,
    })
  );
  await user.click(
    screen.getByRole("button", {
      name: messages.actions.addMcpModal.submitButton.saveLabel,
    })
  );
  await waitFor(() =>
    expect(updateMCPServer).toHaveBeenCalledWith(7, {
      action_policies: {
        raw_tool: "ALWAYS",
        hidden_tool: "ALWAYS",
        disabled_tool: "DENY",
      },
    })
  );
});

it("disables both bulk and per-tool policies without edit permission", async () => {
  const user = setupUser();
  render(<Harness value={{ ...server, permissions: {} }} />);
  await screen.findByRole("switch", { name: "tool-toggle-Display tool" });
  await user.click(
    screen.getByRole("tab", { name: messages.actions.mcpTools.policiesTab })
  );
  expect(
    screen.getByRole("combobox", {
      name: messages.craft.apps.policyEditor.permissions.title,
    })
  ).toBeDisabled();
  for (const button of screen.getAllByRole("button", {
    name: /^(Auto-approve|Ask|Disabled)$/,
  })) {
    expect(button).toBeDisabled();
  }
  expect(screen.getAllByText("Reads records")[0]).toBeVisible();
  expect(updateMCPServer).not.toHaveBeenCalled();
});

it("locks per-tool and bulk policies while saving a policy draft", async () => {
  let completeSave: (() => void) | undefined;
  jest.mocked(updateMCPServer).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        completeSave = () => resolve(server);
      })
  );
  const user = setupUser();
  render(<Harness />);
  await screen.findByRole("switch", { name: "tool-toggle-Display tool" });
  await user.click(
    screen.getByRole("tab", { name: messages.actions.mcpTools.policiesTab })
  );
  const row = screen.getByRole("listitem");
  await user.click(
    within(row).getByRole("button", {
      name: messages.actions.policyToggle.deny.label,
    })
  );
  expect(
    screen.getByRole("combobox", {
      name: messages.craft.apps.policyEditor.permissions.title,
    })
  ).toHaveValue("");
  expect(
    screen.getByRole("combobox", {
      name: messages.craft.apps.policyEditor.permissions.title,
    })
  ).toHaveAttribute(
    "placeholder",
    messages.craft.apps.policyEditor.permissions.customOption
  );
  await user.click(
    screen.getByRole("button", {
      name: messages.actions.addMcpModal.submitButton.saveLabel,
    })
  );
  await waitFor(() => expect(busy).toHaveBeenLastCalledWith(true));
  expect(
    screen.getByRole("combobox", {
      name: messages.craft.apps.policyEditor.permissions.title,
    })
  ).toBeDisabled();
  for (const button of within(row).getAllByRole("button"))
    expect(button).toBeDisabled();
  completeSave?.();
  await waitFor(() => expect(busy).toHaveBeenLastCalledWith(false));
});

it("keeps user management out of the tool permissions tab", async () => {
  render(<Harness />);
  await setupUser().click(
    await screen.findByRole("tab", {
      name: messages.actions.mcpTools.policiesTab,
    })
  );
  expect(
    screen.queryByRole("switch", { name: "Let users manage approval settings" })
  ).not.toBeInTheDocument();
});
