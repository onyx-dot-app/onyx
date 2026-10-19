import { useLayoutEffect, useState } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { userEvent, within } from "storybook/test";
import { SWRConfig, type State } from "swr";
import { Button } from "@opal/components";
import { ToastProvider } from "@opal/layouts";
import ConfigureProviderModal from "@/app/craft/v1/apps/admin/ConfigureProviderModal";
import CreateCustomAppModal from "@/app/craft/v1/apps/admin/CreateCustomAppModal";
import type {
  BuiltInExternalAppDescriptor,
  ExternalAppAdminResponse,
} from "@/app/craft/v1/apps/registry";
import messages from "@/i18n/messages/en.json";

const descriptor: BuiltInExternalAppDescriptor = {
  app_type: "SLACK",
  name: "Slack",
  upstream_url_patterns: ["https://slack.com/api/.*"],
  auth_template: { Authorization: "Bearer {access_token}" },
  required_org_credential_fields: [
    {
      key: "client_id",
      label: "Client ID",
      description: "Found in your Slack app's Basic Information page.",
      secret: false,
    },
    {
      key: "client_secret",
      label: "Client Secret",
      description: "Treat this like a password.",
      secret: true,
    },
  ],
  setup_instructions:
    "Create a Slack app at api.slack.com/apps. Under OAuth & Permissions, add this Onyx instance's /craft/v1/apps/oauth/callback URL to Redirect URLs. Enter the app's Client ID and Client Secret below.",
  actions: [
    {
      action_id: "search",
      normalised_name: "Search messages",
      description: "Find messages in workspace channels.",
      default_policy: "ALWAYS",
    },
    {
      action_id: "send",
      normalised_name: "Send a message",
      description: "Post a message to a channel.",
      default_policy: "ASK",
    },
    {
      action_id: "delete",
      normalised_name: "Delete a message",
      description: "Remove a message posted by the app.",
      default_policy: "DENY",
    },
  ],
};

const app: ExternalAppAdminResponse = {
  id: 42,
  name: "Slack",
  app_type: "SLACK",
  enabled: true,
  upstream_url_patterns: descriptor.upstream_url_patterns,
  auth_template: descriptor.auth_template,
  organization_credentials: {
    client_id: "********",
    client_secret: "********",
  },
  credential_placeholder_keys: ["access_token"],
  actions: descriptor.actions.map((action) => ({
    action_id: action.action_id,
    normalised_name: action.normalised_name,
    description: action.description,
    state: action.default_policy,
  })),
  associated_skills: [],
  is_onyx_managed: false,
  users_can_manage_policies: true,
};

interface CraftAppSetupStoryProps {
  scenario?:
    | "provider-create"
    | "provider-edit"
    | "managed"
    | "custom-create"
    | "custom-edit";
}

function CraftAppSetupStory({
  scenario = "provider-create",
}: CraftAppSetupStoryProps) {
  const [ready, setReady] = useState(false);
  const [open, setOpen] = useState(true);
  const [cache] = useState(() => new Map<string, State>());
  useLayoutEffect(() => {
    const originalFetch = window.fetch;
    const mockFetch: typeof fetch = async (input) => {
      const path = new URL(
        input instanceof Request ? input.url : String(input),
        window.location.origin
      ).pathname;
      if (!path.startsWith("/api/")) return originalFetch(input);
      const value =
        path === "/api/skills"
          ? { builtins: [], customs: [] }
          : path === "/api/settings"
            ? { onyx_craft_enabled: true, onyx_craft_available: true }
            : path === "/api/build/admin/apps"
              ? [app]
              : path.startsWith("/api/build/admin/apps/")
                ? app
                : {};
      return new Response(JSON.stringify(value), {
        headers: { "Content-Type": "application/json" },
      });
    };
    window.fetch = mockFetch;
    setReady(true);
    return () => {
      if (window.fetch === mockFetch) window.fetch = originalFetch;
    };
  }, []);
  if (!ready) return null;
  const existingApp = scenario.endsWith("create")
    ? null
    : scenario === "custom-edit"
      ? {
          ...app,
          name: "Acme API",
          app_type: "CUSTOM" as const,
          upstream_url_patterns: ["https://api.acme.example/*"],
          auth_template: { Authorization: "Bearer {api_key}" },
          organization_credentials: { api_key: "********" },
          credential_placeholder_keys: ["api_key"],
          actions: [],
        }
      : { ...app, is_onyx_managed: scenario === "managed" };
  return (
    <SWRConfig
      value={{
        provider: () => cache,
        shouldRetryOnError: false,
        revalidateOnFocus: false,
      }}
    >
      <ToastProvider>
        <div className="h-screen bg-background-tint-01">
          {!open ? (
            <Button onClick={() => setOpen(true)}>
              {messages.actions.plugins.add.label}
            </Button>
          ) : scenario.startsWith("custom") ? (
            <CreateCustomAppModal
              existingApp={existingApp}
              onClose={() => setOpen(false)}
              onSaved={() => {}}
            />
          ) : (
            <ConfigureProviderModal
              descriptor={descriptor}
              existingApp={existingApp}
              onClose={() => setOpen(false)}
              onSaved={() => {}}
            />
          )}
        </div>
      </ToastProvider>
    </SWRConfig>
  );
}

const meta = {
  title: "Apps/Plugins/Craft App setup",
  component: CraftAppSetupStory,
  parameters: { layout: "fullscreen" },
} satisfies Meta<typeof CraftAppSetupStory>;
export default meta;
type Story = StoryObj<typeof meta>;

export const BuiltIn: Story = {};
export const Tools: Story = {
  play: async () => {
    await userEvent.click(
      await within(document.body).findByRole("tab", {
        name: messages.actions.mcpTools.title,
      })
    );
  },
};
export const ManagedApp: Story = { args: { scenario: "managed" } };
export const ExistingAppSkills: Story = {
  args: { scenario: "provider-edit" },
  play: async () => {
    await userEvent.click(
      await within(document.body).findByRole("tab", {
        name: messages.actions.plugins.craftApp.tabs.skills,
      })
    );
  },
};
export const CustomApp: Story = { args: { scenario: "custom-create" } };
export const CustomAppSkills: Story = {
  args: { scenario: "custom-edit" },
  play: async () => {
    await userEvent.click(
      await within(document.body).findByRole("tab", {
        name: messages.actions.plugins.craftApp.tabs.skills,
      })
    );
  },
};
