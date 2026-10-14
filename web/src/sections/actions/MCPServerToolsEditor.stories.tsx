import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, within, waitFor } from "storybook/test";
import {
  MCPModalStory,
  storyServer,
} from "@/sections/actions/modals/MCPModalStoryHarness";
import messages from "@/i18n/messages/en.json";

const copy = messages.actions;
async function openTools() {
  await userEvent.click(
    await within(document.body).findByRole("tab", {
      name: copy.mcpTools.title,
    })
  );
}
const meta = {
  title: "Apps/Actions/MCP Tools",
  component: MCPModalStory,
  parameters: { layout: "fullscreen", docs: { story: { inline: false } } },
  args: { kind: "detail", scenario: {} },
  play: openTools,
} satisfies Meta<typeof MCPModalStory>;
export default meta;
type Story = StoryObj<typeof meta>;

export const AvailableTools: Story = {};
export const CraftPermissions: Story = {
  args: {
    scenario: {
      craftEnabled: true,
      server: {
        ...storyServer,
        tool_policies: { query_records: "DENY", list_datasets: "ALWAYS" },
      },
    },
  },
  play: async () => {
    await openTools();
    const page = within(document.body);
    await userEvent.click(
      await page.findByRole("tab", { name: copy.mcpTools.policiesTab })
    );
    await expect(await page.findByText("Query records")).toBeVisible();
  },
};
export const Loading: Story = { args: { scenario: { tools: "loading" } } };
export const LoadError: Story = { args: { scenario: { tools: "error" } } };
export const Empty: Story = { args: { scenario: { tools: "empty" } } };
export const EmptyCraftPermissions: Story = {
  args: { scenario: { craftEnabled: true, tools: "empty" } },
  play: async () => {
    await openTools();
    const page = within(document.body);
    await userEvent.click(
      await page.findByRole("tab", { name: copy.mcpTools.policiesTab })
    );
    await expect(
      await page.findByText(messages.craft.apps.mcpPolicy.emptyPolicies)
    ).toBeVisible();
  },
};
export const ReadOnly: Story = {
  args: {
    scenario: {
      tools: "read-only",
      craftEnabled: true,
      server: { ...storyServer, permissions: {} },
    },
  },
};
export const SaveChanges: Story = {
  play: async () => {
    await openTools();
    const page = within(document.body);
    await page.findByRole("tab", { name: copy.mcpTools.enabledTab });
    const toggle = await page.findByRole("switch", {
      name: "tool-toggle-Query records",
    });
    await userEvent.click(toggle);
    await userEvent.click(
      page.getByRole("button", {
        name: copy.addMcpModal.submitButton.saveLabel,
      })
    );
    await waitFor(() =>
      expect(
        page.getByRole("button", {
          name: copy.addMcpModal.submitButton.saveLabel,
        })
      ).toBeDisabled()
    );
    await expect(toggle).not.toBeChecked();
    await expect(page.queryByRole("dialog")).not.toBeInTheDocument();
  },
};
export const SaveError: Story = {
  args: { scenario: { toolsSave: "error" } },
  play: async () => {
    await openTools();
    const page = within(document.body);
    await userEvent.click(
      await page.findByRole("switch", { name: "tool-toggle-Query records" })
    );
    await userEvent.click(
      page.getByRole("button", {
        name: copy.addMcpModal.submitButton.saveLabel,
      })
    );
    await expect(
      await page.findByText("Tool settings could not be saved. Try again.")
    ).toBeVisible();
  },
};
export const Saving: Story = {
  args: { scenario: { toolsSave: "pending" } },
  play: async () => {
    await openTools();
    const page = within(document.body);
    await userEvent.click(
      await page.findByRole("switch", { name: "tool-toggle-Query records" })
    );
    await userEvent.click(
      page.getByRole("button", {
        name: copy.addMcpModal.submitButton.saveLabel,
      })
    );
    await expect(
      page.getByRole("button", {
        name: copy.addMcpModal.submitButton.saveLabel,
      })
    ).toBeDisabled();
  },
};
export const UnsavedChanges: Story = {
  play: async () => {
    await openTools();
    const page = within(document.body);
    await userEvent.click(
      await page.findByRole("switch", { name: "tool-toggle-Query records" })
    );
    await userEvent.click(
      page.getByRole("link", { name: copy.mcpDetail.back })
    );
    await expect(
      await page.findByRole("dialog", {
        name: messages.chat.modals.unsavedChanges.header.title,
      })
    ).toBeVisible();
  },
};
