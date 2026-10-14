import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, within, waitFor } from "storybook/test";
import {
  MCPModalStory,
  storyServer,
} from "@/sections/actions/modals/MCPModalStoryHarness";
import messages from "@/i18n/messages/en.json";

const copy = messages.actions.addMcpModal;
const meta = {
  title: "Apps/Actions/MCP Setup Flow",
  component: MCPModalStory,
  parameters: { layout: "fullscreen", docs: { story: { inline: false } } },
  args: { kind: "add", scenario: {} },
} satisfies Meta<typeof MCPModalStory>;
export default meta;
type Story = StoryObj<typeof meta>;

export const CreateAndContinue: Story = {
  play: async () => {
    const page = within(document.body);
    const dialog = await page.findByRole("dialog");
    await userEvent.type(
      await page.findByPlaceholderText(copy.name.placeholder),
      "Analytics MCP"
    );
    await userEvent.type(
      page.getByPlaceholderText("https://your-mcp-server.com/mcp"),
      storyServer.server_url
    );
    await userEvent.click(
      page.getByRole("button", { name: messages.actions.mcpSetup.continue })
    );
    await expect(await page.findByRole("tab", { name: "OAuth" })).toBeVisible();
    await expect(page.getByRole("dialog")).toBe(dialog);
  },
};

export const DirectAuthentication: Story = {
  args: { kind: "auth", scenario: {} },
};

export const BackPreservesDraft: Story = {
  args: { kind: "auth", scenario: { wizard: true } },
  play: async () => {
    const page = within(document.body);
    const dialog = await page.findByRole("dialog");
    await userEvent.click(
      await page.findByRole("tab", { name: "Use your own OAuth client" })
    );
    await userEvent.type(
      page.getByRole("textbox", { name: /^Client ID/ }),
      "draft-client"
    );
    await userEvent.click(
      page.getByRole("button", { name: messages.actions.mcpSetup.back })
    );
    const name = await page.findByPlaceholderText(copy.name.placeholder);
    await userEvent.clear(name);
    await userEvent.type(name, "Updated analytics");
    await userEvent.click(
      page.getByRole("button", { name: messages.actions.mcpSetup.continue })
    );
    await expect(
      await page.findByRole("textbox", { name: /^Client ID/ })
    ).toHaveValue("draft-client");
    await expect(page.getByRole("dialog")).toBe(dialog);
  },
};

export const ChangedUrlResetsAuthentication: Story = {
  args: {
    kind: "auth",
    scenario: {
      wizard: true,
      server: {
        ...storyServer,
        admin_credentials: {
          client_id: "previous-client",
          client_secret: "********",
        },
      },
    },
  },
  play: async () => {
    const page = within(document.body);
    await page.findByDisplayValue("previous-client");
    await userEvent.click(
      page.getByRole("button", { name: messages.actions.mcpSetup.back })
    );
    const url = await page.findByPlaceholderText(
      "https://your-mcp-server.com/mcp"
    );
    await userEvent.clear(url);
    await userEvent.type(url, "https://new.example.com/mcp");
    await userEvent.click(
      page.getByRole("button", { name: messages.actions.mcpSetup.continue })
    );
    await expect(
      await page.findByRole("tab", { name: "Set up automatically" })
    ).toHaveAttribute("aria-selected", "true");
    await userEvent.click(
      page.getByRole("tab", { name: "Use your own OAuth client" })
    );
    await expect(page.getByRole("textbox", { name: /^Client ID/ })).toHaveValue(
      ""
    );
  },
};

export const SaveDetailsOnPage: Story = {
  args: { kind: "detail", scenario: {} },
  play: async () => {
    const page = within(document.body);
    await userEvent.click(
      await page.findByRole("tab", {
        name: messages.actions.mcpDetail.configuration,
      })
    );
    const name = await page.findByRole("textbox", { name: copy.name.title });
    await userEvent.type(name, " updated");
    await userEvent.click(
      page.getByRole("button", { name: copy.submitButton.saveLabel })
    );
    await waitFor(() =>
      expect(page.queryByRole("dialog")).not.toBeInTheDocument()
    );
    await expect(await page.findByText("Analytics MCP updated")).toBeVisible();
  },
};

export const UnsavedChanges: Story = {
  args: { kind: "add", scenario: { edit: true } },
  play: async () => {
    const page = within(document.body);
    await userEvent.type(
      await page.findByRole("textbox", { name: copy.name.title }),
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

export const AuthenticationOpensDetailPage: Story = {
  args: { kind: "auth", scenario: { wizard: true } },
  play: async () => {
    const page = within(document.body);
    await page.findByRole("dialog");
    const save = await page.findByTestId("mcp-auth-connect-button");
    await waitFor(() => expect(save).toBeEnabled());
    await userEvent.click(save);
    await expect(
      await page.findByRole("tab", {
        name: messages.actions.mcpTools.title,
      })
    ).toBeVisible();
    await expect(page.queryByRole("dialog")).not.toBeInTheDocument();
  },
};
