import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, within, waitFor } from "storybook/test";
import {
  MCPSetupModalStory,
  storyServer,
} from "@/views/admin/PluginsPage/components/mcp/MCPModalStoryHarness";
import messages from "@/i18n/messages/en.json";

const copy = messages.actions.mcpSetup;
const meta = {
  title: "Apps/Actions/MCP Setup Flow",
  component: MCPSetupModalStory,
  parameters: { layout: "fullscreen", docs: { story: { inline: false } } },
  args: { scenario: {} },
} satisfies Meta<typeof MCPSetupModalStory>;
export default meta;
type Story = StoryObj<typeof meta>;

async function enterUrl() {
  const page = within(document.body);
  const input = await page.findByRole("textbox", { name: /^MCP Server URL/ });
  await userEvent.type(input, storyServer.server_url);
  return page;
}
async function continueFromUrl() {
  const page = await enterUrl();
  const next = page.getByRole("button", { name: copy.continue });
  await waitFor(() => expect(next).toBeEnabled());
  await userEvent.click(next);
  return page;
}
async function continueToDetails() {
  return continueFromUrl();
}

export const UrlOnly: Story = {};
export const CreateAndContinue: Story = {
  play: async () => {
    const page = await continueFromUrl();
    await expect(
      page.queryByRole("textbox", { name: "Server Name" })
    ).not.toBeInTheDocument();
    await expect(
      page.getByRole("combobox", {
        name: messages.actions.mcpAuthModal.authType.label,
      })
    ).toHaveValue("OAuth");
    await expect(page.getByRole("dialog")).toBeVisible();
  },
};
export const PublicDetected: Story = {
  args: { scenario: { probe: "public" } },
  play: async () => {
    const page = await enterUrl();
    await expect(await page.findByText(copy.publicDetected)).toBeVisible();
    await expect(page.getAllByRole("textbox")).toHaveLength(2);
  },
};
export const PublicServer: Story = {
  args: { scenario: { probe: "public" } },
  play: async () => {
    const page = await continueFromUrl();
    await expect(
      page.getByRole("combobox", {
        name: messages.actions.mcpAuthModal.authType.label,
      })
    ).toHaveValue("No authentication");
    await expect(
      page.getByRole("button", { name: copy.connect })
    ).toBeEnabled();
  },
};
export const OAuthDetected: Story = {
  play: async () => {
    const page = await enterUrl();
    await expect(await page.findByText(copy.oauthDetected)).toBeVisible();
  },
};
export const OAuthServer: Story = {
  play: async () => {
    const page = await continueFromUrl();
    await expect(
      page.getByRole("combobox", {
        name: messages.actions.mcpAuthModal.authType.label,
      })
    ).toHaveValue("OAuth");
    await expect(
      page.getByRole("radio", { name: "Set up automatically" })
    ).toHaveAttribute("aria-checked", "true");
  },
};
export const OAuthOwnClient: Story = {
  args: { scenario: { discovery: "unsupported" } },
  play: async () => {
    const page = await continueFromUrl();
    await expect(
      page.getByRole("radio", { name: "Use your own OAuth client" })
    ).toHaveAttribute("aria-checked", "true");
  },
};
export const ManualAuthentication: Story = {
  args: { scenario: { probe: "auth_unknown" } },
  play: async () => {
    const page = await continueFromUrl();
    await expect(
      page.getByRole("combobox", {
        name: messages.actions.mcpAuthModal.authType.label,
      })
    ).not.toHaveValue("OAuth");
    await expect(
      page.getByRole("button", { name: copy.connect })
    ).toBeDisabled();
  },
};
export const UnreachableServer: Story = {
  args: { scenario: { probe: "unreachable" } },
  play: async () => {
    const page = await enterUrl();
    await expect(await page.findByRole("alert")).toHaveTextContent(
      copy.unreachable
    );
    await expect(
      page.getByRole("button", { name: copy.continue })
    ).toBeDisabled();
    await expect(
      page.getByRole("button", { name: copy.configureManually })
    ).toBeEnabled();
  },
};
export const BlockedServer: Story = {
  args: { scenario: { probe: "blocked" } },
  play: async () => {
    const page = await enterUrl();
    await expect(await page.findByRole("alert")).toHaveTextContent(
      copy.blocked
    );
    await expect(
      page.queryByRole("button", { name: copy.configureManually })
    ).not.toBeInTheDocument();
  },
};
export const CheckingServer: Story = {
  args: { scenario: { probe: "checking" } },
  play: async () => {
    const page = await enterUrl();
    await expect(await page.findByRole("status")).toHaveTextContent(
      copy.contactingServer
    );
    await expect(
      page.getByRole("button", { name: copy.continue })
    ).toBeDisabled();
  },
};
export const DetectingAuthentication: Story = {
  args: { scenario: { probe: "auth-checking" } },
  play: async () => {
    const page = await enterUrl();
    await expect(await page.findByRole("status")).toHaveTextContent(
      copy.detectingAuthentication
    );
    await expect(
      page.getByRole("button", { name: copy.continue })
    ).toBeDisabled();
  },
};
export const BackPreservesDraft: Story = {
  play: async () => {
    const page = await continueFromUrl();
    await userEvent.click(
      page.getByRole("radio", { name: "Use your own OAuth client" })
    );
    await userEvent.type(
      page.getByRole("textbox", { name: /^Client ID/ }),
      "draft-client"
    );
    await userEvent.click(page.getByRole("button", { name: copy.back }));
    await userEvent.click(page.getByRole("button", { name: copy.continue }));
    await expect(page.getByRole("textbox", { name: /^Client ID/ })).toHaveValue(
      "draft-client"
    );
  },
};
export const ChangedUrlResetsAuthentication: Story = {
  play: async () => {
    const page = await continueFromUrl();
    await userEvent.click(
      page.getByRole("radio", { name: "Use your own OAuth client" })
    );
    await userEvent.type(
      page.getByRole("textbox", { name: /^Client ID/ }),
      "previous-client"
    );
    await userEvent.click(page.getByRole("button", { name: copy.back }));
    const url = page.getByRole("textbox", { name: /^MCP Server URL/ });
    await userEvent.clear(url);
    await userEvent.type(url, "https://new.example.com/mcp");
    const next = page.getByRole("button", { name: copy.continue });
    await waitFor(() => expect(next).toBeEnabled());
    await userEvent.click(next);
    await userEvent.click(
      page.getByRole("radio", { name: "Use your own OAuth client" })
    );
    await expect(page.getByRole("textbox", { name: /^Client ID/ })).toHaveValue(
      ""
    );
  },
};
export const ScopedManager: Story = {
  args: { scenario: { scoped: true, probe: "public" } },
  play: async () => {
    await continueToDetails();
  },
};
export const SaveError: Story = {
  args: { scenario: { probe: "public", submit: "save-error" } },
  play: async () => {
    const page = await continueToDetails();
    await userEvent.click(page.getByRole("button", { name: copy.connect }));
    await expect(await page.findByRole("alert")).toBeVisible();
  },
};
export const FinalDetails: Story = {
  args: { scenario: { probe: "public" } },
  play: async () => {
    const page = await continueToDetails();
    await expect(
      page.queryByRole("textbox", { name: "Server Name" })
    ).not.toBeInTheDocument();
    await expect(page.queryByRole("tab")).not.toBeInTheDocument();
    await expect(
      page.getByRole("button", { name: copy.connect })
    ).toBeEnabled();
  },
};
export const CancelDiscardsDraft: Story = {
  play: async () => {
    const page = await enterUrl();
    await userEvent.click(page.getByRole("button", { name: "Cancel" }));
    await expect(
      page.queryByRole("dialog", {
        name: messages.chat.modals.unsavedChanges.header.title,
      })
    ).not.toBeInTheDocument();
  },
};
