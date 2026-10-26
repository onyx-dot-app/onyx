import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, within, waitFor } from "storybook/test";
import {
  MCPModalStory,
  storyServer,
  type MCPStoryScenario,
} from "@/sections/actions/modals/MCPModalStoryHarness";
import {
  MCPAuthenticationType,
  MCPAuthenticationPerformer,
  MCPOAuthProviderMode,
} from "@/lib/mcp/types";
import messages from "@/i18n/messages/en.json";
const copy = messages.actions.mcpAuthModal;
const meta = {
  title: "Apps/Actions/MCP Authentication",
  component: MCPModalStory,
  parameters: { layout: "fullscreen", docs: { story: { inline: false } } },
  args: { kind: "auth", scenario: {} },
} satisfies Meta<typeof MCPModalStory>;
export default meta;
type Story = StoryObj<typeof meta>;
const own = {
  ...storyServer,
  admin_credentials: { client_id: "analytics-desktop" },
};
function scenario(value: MCPStoryScenario): Story {
  return { args: { scenario: value } };
}
async function submit() {
  const page = within(document.body);
  const button = await page.findByTestId("mcp-auth-connect-button");
  await waitFor(() => expect(button).toBeEnabled());
  await userEvent.click(button);
}

export const OAuthAutomatic: Story = {};
export const OAuthOwnClient = scenario({ server: own });
export const OAuthSavedMasked = scenario({
  server: {
    ...own,
    admin_credentials: {
      client_id: "analytics-desktop",
      client_secret: "********",
    },
  },
});
export const OAuthManualEndpoints = scenario({
  server: {
    ...own,
    oauth_provider_mode: MCPOAuthProviderMode.KNOWN_PROVIDER,
    oauth_authorization_endpoint: "https://identity.example.com/authorize",
    oauth_token_endpoint: "https://identity.example.com/token",
    oauth_scopes_override: ["analytics.read"],
    oauth_additional_auth_params: { prompt: "consent" },
  },
});
export const DiscoveryLoading = scenario({ discovery: "loading" });
export const DiscoveryMissing = scenario({ discovery: "metadata_missing" });
export const DiscoveryUnreachable = scenario({ discovery: "unreachable" });
export const DiscoveryUnsupported: Story = {
  ...scenario({ discovery: "unsupported" }),
  play: async () => {
    const page = within(document.body);
    await page.findByLabelText(copy.clientId.label, { exact: false });
    await userEvent.click(
      page.getByRole("radio", { name: copy.oauthSetup.automatic.label })
    );
    await page.findByText(copy.discovery.requiresClient);
  },
};
export const DiscoveryRetry: Story = {
  ...scenario({ discovery: "retry" }),
  play: async () => {
    const page = within(document.body);
    await userEvent.click(
      await page.findByRole("button", { name: copy.discovery.retry })
    );
    await page.findByRole("radio", { name: copy.oauthSetup.automatic.label });
  },
};
export const ApiPersonal = scenario({
  server: { ...storyServer, auth_type: MCPAuthenticationType.API_TOKEN },
});
export const ApiShared = scenario({
  server: {
    ...storyServer,
    auth_type: MCPAuthenticationType.API_TOKEN,
    auth_performer: MCPAuthenticationPerformer.ADMIN,
    admin_credentials: { api_key: "********" },
  },
});
export const ApiCustomHeaders: Story = {
  ...scenario({
    server: {
      ...storyServer,
      auth_type: MCPAuthenticationType.API_TOKEN,
      auth_template: {
        headers: {
          Authorization: "Bearer {api_key}",
          "X-Workspace": "{workspace}",
        },
        required_fields: ["api_key", "workspace"],
      },
      user_credentials: { api_key: "********", workspace: "data-team" },
    },
  }),
  play: async () => {
    const page = within(document.body);
    await userEvent.click(
      await page.findByRole("button", {
        name: `Expand ${copy.advancedSettings.title}`,
      })
    );
  },
};
export const NoAuthentication = scenario({
  server: { ...storyServer, auth_type: MCPAuthenticationType.NONE },
});
export const PassThrough = scenario({
  server: { ...storyServer, auth_type: MCPAuthenticationType.PT_OAUTH },
});
export const SettingsLoading = scenario({ load: "loading" });
export const SettingsLoadError = scenario({ load: "error" });
export const ClientValidation: Story = {
  play: async () => {
    const page = within(document.body);
    await userEvent.click(
      await page.findByRole("radio", { name: copy.oauthSetup.ownClient.label })
    );
    const client = page.getByLabelText(copy.clientId.label, { exact: false });
    await userEvent.type(client, "temporary");
    await userEvent.clear(client);
    await userEvent.tab();
    await expect(page.getByTestId("mcp-auth-connect-button")).toBeDisabled();
  },
};
export const Saving: Story = {
  ...scenario({ submit: "pending" }),
  play: submit,
};
export const SaveError: Story = {
  ...scenario({ submit: "save-error" }),
  play: submit,
};
export const RegistrationError: Story = {
  ...scenario({ submit: "oauth-error" }),
  play: submit,
};
export const ToolDiscoveryError: Story = {
  ...scenario({
    submit: "tools-error",
    server: { ...storyServer, auth_type: MCPAuthenticationType.NONE },
  }),
  play: submit,
};

export const SharedHeaderValidation: Story = {
  ...ApiShared,
  play: async () => {
    const page = within(document.body);
    await userEvent.click(
      await page.findByRole("button", {
        name: `Expand ${copy.advancedSettings.title}`,
      })
    );
    const header = page.getByDisplayValue("Bearer {api_key}");
    await userEvent.clear(header);
    await userEvent.type(header, "fixed-value");
    await expect(page.getByTestId("mcp-auth-connect-button")).toBeDisabled();
  },
};
export const ChangeMethodAfterOAuthError: Story = {
  ...scenario({ submit: "oauth-error" }),
  play: async () => {
    await submit();
    const page = within(document.body);
    await page.findByRole("alert");
    await userEvent.click(
      page.getByRole("combobox", { name: copy.authType.label })
    );
    await userEvent.click(
      page.getByRole("option", { name: copy.authType.none.label })
    );
    await expect(page.queryByRole("alert")).not.toBeInTheDocument();
  },
};
export const SharedToPersonalClearsSecret: Story = {
  ...ApiShared,
  play: async () => {
    const page = within(document.body);
    await userEvent.click(page.getByRole("combobox", { name: "Credentials" }));
    await userEvent.click(
      page.getByRole("option", { name: copy.apiKeyTabs.perUser.label })
    );
    await expect(
      page.getByLabelText(copy.sharedApiKey.label, { selector: "input" })
    ).toHaveValue("");
  },
};
export const PassThroughUnavailable = scenario({ oauthEnabled: false });
export const AdvancedConnectionSettings: Story = {
  play: async () => {
    const page = within(document.body);
    await userEvent.click(
      await page.findByRole("button", {
        name: `Expand ${copy.advancedSettings.title}`,
      })
    );
  },
};
