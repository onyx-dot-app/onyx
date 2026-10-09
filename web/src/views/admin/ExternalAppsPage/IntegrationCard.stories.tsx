import type { Meta, StoryObj } from "@storybook/react-vite";
import { SvgSlack } from "@opal/logos";
import { SvgPlug } from "@opal/icons";
import IntegrationCard from "@/views/admin/ExternalAppsPage/IntegrationCard";
import type { ConfiguredIntegration } from "@/views/admin/ExternalAppsPage/interfaces";

const APP: ConfiguredIntegration = {
  key: "app-1",
  isCustom: false,
  logo: SvgSlack,
  name: "Slack",
  facts: ["7 actions", "2 custom skills"],
  warnings: [],
  enabled: true,
  toggleEnabled: async () => {},
  edit: () => {},
  remove: { run: async () => {}, retainedCustomSkillCount: 2 },
};

const meta: Meta<typeof IntegrationCard> = {
  title: "Apps/Craft/Admin/Integration Card",
  component: IntegrationCard,
  tags: ["autodocs"],
  decorators: [
    (Story) => (
      <div className="w-[820px]">
        <Story />
      </div>
    ),
  ],
  args: { integration: APP },
};

export default meta;
type Story = StoryObj<typeof IntegrationCard>;

/** Hover the row to reveal the switch's scope label and the ⋯ menu holds
 * Edit and Delete. */
export const EnabledApp: Story = {};

/** Off rows dim their content; controls keep full opacity. */
export const DisabledApp: Story = {
  args: { integration: { ...APP, enabled: false } },
};

export const CustomApp: Story = {
  args: {
    integration: {
      ...APP,
      key: "app-2",
      isCustom: true,
      logo: SvgPlug,
      name: "Internal billing API",
      facts: ["2 upstream patterns", "org credentials set", "1 custom skill"],
    },
  },
};

export const InvalidSkillWarning: Story = {
  args: { integration: { ...APP, warnings: ["invalid skill"] } },
};

/** Orphaned provider: no descriptor, so the menu offers Delete only. */
export const OrphanedProvider: Story = {
  args: {
    integration: {
      ...APP,
      warnings: ["invalid skill", "provider unavailable"],
      edit: null,
    },
  },
};

/** Onyx-managed built-in: editable policies, never deletable. */
export const OnyxManaged: Story = {
  args: {
    integration: {
      ...APP,
      facts: ["provided by Onyx", "7 actions", "no custom skills"],
      remove: null,
    },
  },
};

/** MCP server row: tool facts, policy editing only, no delete. */
export const McpServer: Story = {
  args: {
    integration: {
      ...APP,
      key: "mcp-1",
      logo: SvgPlug,
      name: "Atlassian",
      facts: ["31 tools"],
      remove: null,
    },
  },
};

/** No available actions: the ⋯ trigger renders disabled to keep alignment. */
export const NoActions: Story = {
  args: { integration: { ...APP, edit: null, remove: null } },
};
