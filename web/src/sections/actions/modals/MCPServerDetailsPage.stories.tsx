import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, within } from "storybook/test";
import {
  MCPModalStory,
  storyServer,
  type MCPStoryScenario,
} from "@/sections/actions/modals/MCPModalStoryHarness";
import messages from "@/i18n/messages/en.json";
const copy = messages.actions.addMcpModal;
const meta = {
  title: "Apps/Actions/MCP Server Details",
  component: MCPModalStory,
  parameters: { layout: "fullscreen", docs: { story: { inline: false } } },
  args: { kind: "add", scenario: { edit: true } },
} satisfies Meta<typeof MCPModalStory>;
export default meta;
type Story = StoryObj<typeof meta>;
function scenario(value: MCPStoryScenario): Story {
  return { args: { scenario: { edit: true, ...value } } };
}
const restricted = { ...storyServer, is_public: false, groups: [1, 2] };
async function fillAndSubmit() {
  const page = within(document.body);
  const name = await page.findByPlaceholderText(copy.name.placeholder);
  await userEvent.clear(name);
  await userEvent.type(name, "Updated analytics");
  await userEvent.click(
    page.getByRole("button", { name: copy.submitButton.saveLabel })
  );
}
export const CraftAvailable: Story = {
  args: { kind: "detail", scenario: { craftEnabled: true } },
  play: async () => {
    const page = within(document.body);
    await expect(
      await page.findByRole("switch", { name: new RegExp(copy.craft.title) })
    ).toBeChecked();
  },
};
export const CraftDisabledForServer: Story = {
  args: {
    kind: "detail",
    scenario: {
      craftEnabled: true,
      server: { ...storyServer, available_in_craft: false },
    },
  },
  play: async () => {
    const page = within(document.body);
    const toggle = await page.findByRole("switch", {
      name: new RegExp(copy.craft.title),
    });
    await expect(toggle).not.toBeChecked();
    await userEvent.click(toggle);
    await expect(toggle).toBeChecked();
  },
};
export const EditPublic = scenario({ edit: true });
export const UserGroups = scenario({ edit: true, server: restricted });
export const FiftyGroups = scenario({
  edit: true,
  server: {
    ...restricted,
    groups: Array.from({ length: 50 }, (_, index) => index + 1),
  },
});
export const RetainedUserGrants = scenario({
  edit: true,
  server: { ...restricted, users: ["existing-user-1", "existing-user-2"] },
});
export const ScopedManager = scenario({ scoped: true });
export const CommunityPlan = scenario({ community: true });
export const GroupsLoading = scenario({
  edit: true,
  server: restricted,
  groups: "loading",
});
export const GroupsError = scenario({
  edit: true,
  server: restricted,
  groups: "error",
});
export const InvalidUrl: Story = {
  play: async () => {
    const page = within(document.body);
    await userEvent.clear(
      await page.findByPlaceholderText("https://your-mcp-server.com/mcp")
    );
    await userEvent.type(
      await page.findByPlaceholderText("https://your-mcp-server.com/mcp"),
      "not-a-url"
    );
    await userEvent.tab();
  },
};
export const Saving: Story = {
  ...scenario({ submit: "pending" }),
  play: fillAndSubmit,
};
export const SaveError: Story = {
  ...scenario({ submit: "save-error" }),
  play: fillAndSubmit,
};

export const RequiredName: Story = {
  play: async () => {
    const page = within(document.body);
    const name = await page.findByPlaceholderText(copy.name.placeholder);
    await userEvent.type(name, "Temporary");
    await userEvent.clear(name);
    await userEvent.tab();
  },
};

export const DefaultChatDisabled: Story = {
  args: {
    kind: "detail",
    scenario: {
      edit: true,
      craftEnabled: true,
      server: storyServer,
      defaultToolIds: [],
    },
  },
  play: async () => {
    const page = within(document.body);
    const toggle = await page.findByRole("switch", {
      name: new RegExp(copy.defaultChat.title),
    });
    await expect(toggle).not.toBeChecked();
    await userEvent.click(toggle);
    await expect(toggle).toBeChecked();
  },
};
