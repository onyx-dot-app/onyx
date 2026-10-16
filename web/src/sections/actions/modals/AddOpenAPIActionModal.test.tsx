/** @jest-environment jsdom */
import { render, screen, setupUser } from "@tests/setup/test-utils";
import AddOpenAPIActionModal from "@/sections/actions/modals/AddOpenAPIActionModal";
import type { ToolSnapshot } from "@/lib/tools/types";

jest.mock("@opal/components", () => ({
  ...jest.requireActual("@opal/components"),
  useModal: () => ({ isOpen: true, toggle: jest.fn() }),
}));
jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({ onyx_craft_available: true }),
}));
jest.mock("@/lib/permissions/hooks", () => ({
  usePermissionAuthority: () => ({ isGlobalHolder: true }),
}));
jest.mock("@/lib/tools/svc", () => ({
  validateToolDefinition: async () => ({ data: [], error: null }),
}));

const tool: ToolSnapshot = {
  id: 42,
  name: "API",
  display_name: "API",
  description: "API actions",
  definition: null,
  custom_headers: [],
  in_code_tool_id: null,
  passthrough_auth: false,
  enabled: false,
  chat_selectable: true,
  agent_creation_selectable: true,
  default_enabled: false,
  permissions: { edit: true, delete: true, toggle: true, authenticate: true },
};

it.each([null, 7])(
  "allows authentication configuration for disabled actions with OAuth config %s",
  async (oauth_config_id) => {
    const user = setupUser();
    const onEditAuthentication = jest.fn();
    const existingTool = { ...tool, oauth_config_id };
    render(
      <AddOpenAPIActionModal
        existingTool={existingTool}
        onEditAuthentication={onEditAuthentication}
      />
    );
    expect(
      screen.getByText(
        oauth_config_id
          ? "Authentication configured"
          : "No authentication configured"
      )
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Authenticated & Enabled")
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("checkbox", { name: "Enable in Craft" })
    ).not.toBeChecked();
    await user.click(
      screen.getByRole("button", { name: "Configure authentication" })
    );
    expect(onEditAuthentication).toHaveBeenCalledWith(existingTool);
    expect(existingTool.enabled).toBe(false);
  }
);
