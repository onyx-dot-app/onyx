import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, within, waitFor } from "storybook/test";
import {
  MCPModalStory,
  storyServer,
} from "@/sections/actions/modals/MCPModalStoryHarness";
import { MCPServerStatus } from "@/lib/mcp/types";
import messages from "@/i18n/messages/en.json";

const meta = {
  title: "Apps/Actions/MCP Server Page",
  component: MCPModalStory,
  parameters: { layout: "fullscreen" },
  args: {
    kind: "detail",
    scenario: {
      craftEnabled: true,
      server: { ...storyServer, status: MCPServerStatus.CONNECTED },
    },
  },
} satisfies Meta<typeof MCPModalStory>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Ready: Story = {};
export const SetupIncomplete: Story = { args: { scenario: {} } };
export const WithoutCraft: Story = {
  args: { scenario: { craftEnabled: false } },
};
export const Loading: Story = { args: { scenario: { load: "loading" } } };
export const LoadError: Story = { args: { scenario: { load: "error" } } };
export const ReadOnly: Story = {
  args: {
    scenario: {
      craftEnabled: true,
      server: { ...storyServer, permissions: {} },
      tools: "read-only",
    },
  },
};
export const EditServer: Story = {
  play: async () => {
    const page = within(document.body);
    await userEvent.click(
      await page.findByRole("tab", {
        name: messages.actions.mcpDetail.configuration,
      })
    );
    await expect(
      await page.findByRole("textbox", {
        name: messages.actions.addMcpModal.name.title,
      })
    ).toHaveValue(storyServer.name);
  },
};
export const EditAuthentication: Story = {
  play: async () => {
    const page = within(document.body);
    await userEvent.click(
      await page.findByRole("tab", {
        name: messages.actions.mcpDetail.authentication,
      })
    );
    await expect(await page.findByRole("tab", { name: "OAuth" })).toBeVisible();
  },
};
export const AvailabilityPersists: Story = {
  play: async () => {
    const page = within(document.body);
    const toggle = await page.findByRole("switch", {
      name: new RegExp(messages.actions.addMcpModal.defaultChat.title),
    });
    await expect(toggle).not.toBeChecked();
    await userEvent.click(toggle);
    await waitFor(() => expect(toggle).toBeChecked());
    await expect(toggle).toBeEnabled();
  },
};

export const PartialDefaultChatSelection: Story = {
  args: { scenario: { defaultToolIds: [2, 99] } },
  play: async () => {
    const page = within(document.body);
    const toggle = await page.findByRole("switch", {
      name: new RegExp(messages.actions.addMcpModal.defaultChat.title),
    });
    await waitFor(() => expect(toggle).toBeChecked());
  },
};

export const ScopedManagerDefaultChatReadOnly: Story = {
  args: { scenario: { scoped: true, craftEnabled: true } },
  play: async () => {
    const page = within(document.body);
    await page.findByRole("textbox", {
      name: messages.actions.addMcpModal.name.title,
    });
    await expect(
      page.queryByRole("switch", {
        name: new RegExp(messages.actions.addMcpModal.defaultChat.title),
      })
    ).not.toBeInTheDocument();
  },
};

export const DraftsSurviveTabChanges: Story = {
  play: async () => {
    const page = within(document.body);
    const name = await page.findByRole("textbox", {
      name: messages.actions.addMcpModal.name.title,
    });
    await userEvent.type(name, " draft");
    await userEvent.click(
      page.getByRole("tab", { name: messages.actions.mcpDetail.authentication })
    );
    await userEvent.click(
      await page.findByRole("tab", { name: "Use your own OAuth client" })
    );
    const client = page.getByRole("textbox", { name: /^Client ID/ });
    await userEvent.type(client, "draft-client");
    await userEvent.click(
      page.getByRole("tab", { name: messages.actions.mcpDetail.configuration })
    );
    await expect(
      page.getByRole("textbox", {
        name: messages.actions.addMcpModal.name.title,
      })
    ).toHaveValue("Analytics MCP draft");
    await userEvent.click(
      page.getByRole("tab", { name: messages.actions.mcpDetail.authentication })
    );
    await expect(page.getByRole("textbox", { name: /^Client ID/ })).toHaveValue(
      "draft-client"
    );
    await expect(page.queryByRole("dialog")).not.toBeInTheDocument();
  },
};

export const UnsavedServerChanges: Story = {
  play: async () => {
    const page = within(document.body);
    await userEvent.type(
      await page.findByRole("textbox", {
        name: messages.actions.addMcpModal.name.title,
      }),
      " draft"
    );
    await userEvent.click(
      page.getByRole("link", { name: messages.actions.mcpDetail.back })
    );
    await expect(
      await page.findByRole("dialog", {
        name: messages.chat.modals.unsavedChanges.header.title,
      })
    ).toBeVisible();
  },
};
