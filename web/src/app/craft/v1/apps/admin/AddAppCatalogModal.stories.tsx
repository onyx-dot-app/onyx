import type { Meta, StoryObj } from "@storybook/react-vite";
import AddAppCatalogModal from "@/app/craft/v1/apps/admin/AddAppCatalogModal";
import type { BuiltInExternalAppDescriptor } from "@/app/craft/v1/apps/registry";

function descriptor(
  app_type: BuiltInExternalAppDescriptor["app_type"],
  name: string
): BuiltInExternalAppDescriptor {
  return {
    app_type,
    name,
    upstream_url_patterns: [],
    auth_template: {},
    required_org_credential_fields: [],
    setup_instructions: "",
    actions: [],
  };
}

const meta: Meta<typeof AddAppCatalogModal> = {
  title: "Apps/Craft/Admin/Add App Catalog",
  component: AddAppCatalogModal,
  args: {
    onClose: () => {},
    onPickProvider: () => {},
    onPickCustom: () => {},
    descriptors: [
      descriptor("SLACK", "Slack"),
      descriptor("GOOGLE_DRIVE", "Google Drive"),
      descriptor("GMAIL", "Gmail"),
      descriptor("LINEAR", "Linear"),
      descriptor("GITHUB", "GitHub"),
      descriptor("NOTION", "Notion"),
    ],
  },
};

export default meta;
type Story = StoryObj<typeof AddAppCatalogModal>;

export const WithProviders: Story = {};

/** Every built-in already configured — only the custom-app path remains. */
export const AllProvidersConfigured: Story = {
  args: { descriptors: [] },
};
