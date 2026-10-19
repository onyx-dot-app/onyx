import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, within } from "storybook/test";
import {
  MCPModalStory,
  storyServer,
} from "@/sections/actions/modals/MCPModalStoryHarness";
import { MCPServerStatus } from "@/lib/mcp/types";
import messages from "@/i18n/messages/en.json";

const meta = {
  title: "Apps/Plugins/MCP Plugin Details",
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
    await expect(
      await page.findByRole("combobox", {
        name: messages.actions.mcpAuthModal.authType.label,
      })
    ).toBeVisible();
  },
};
export const NoLifecycleControls: Story = {
  play: async () => {
    const page = within(document.body);
    await page.findByRole("textbox", {
      name: messages.actions.addMcpModal.name.title,
    });
    await expect(
      page.queryByRole("button", {
        name: new RegExp(
          `${messages.actions.plugins.controls.enable}|${messages.actions.plugins.controls.disable}|${messages.actions.plugins.controls.manageAvailability}`
        ),
      })
    ).not.toBeInTheDocument();
    await expect(
      page.queryByRole("button", {
        name: messages.actions.mcpCard.deleteModal.submitButton.label,
      })
    ).not.toBeInTheDocument();
    await expect(page.getAllByRole("dialog")).toHaveLength(1);
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
      page.getByRole("tab", {
        name: messages.actions.mcpDetail.authentication,
      })
    );
    await userEvent.click(
      await page.findByRole("radio", { name: "Use your own OAuth client" })
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
    await expect(page.getAllByRole("dialog")).toHaveLength(1);
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
    await userEvent.click(page.getByRole("button", { name: "Close" }));
    await expect(
      await page.findByRole("dialog", {
        name: messages.chat.modals.unsavedChanges.header.title,
      })
    ).toBeVisible();
  },
};
