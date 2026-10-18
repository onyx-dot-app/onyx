import { useLayoutEffect, useState } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { SWRConfig, type State } from "swr";
import { UserProvider } from "@/providers/UserProvider";
import { Permission } from "@/lib/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import type {
  BuiltInExternalAppDescriptor,
  ExternalAppType,
} from "@/app/craft/v1/apps/registry";
import PluginAddCatalogModal from "@/views/admin/PluginsPage/components/PluginAddCatalogModal";

const providers: { app_type: ExternalAppType; name: string }[] = [
  { app_type: "SLACK", name: "Slack" },
  { app_type: "GOOGLE_CALENDAR", name: "Google Calendar" },
  { app_type: "GOOGLE_DRIVE", name: "Google Drive" },
  { app_type: "GMAIL", name: "Gmail" },
  { app_type: "LINEAR", name: "Linear" },
  { app_type: "GITHUB", name: "GitHub" },
  { app_type: "HUBSPOT", name: "HubSpot" },
  { app_type: "NOTION", name: "Notion" },
];
const descriptors: BuiltInExternalAppDescriptor[] = providers.map(
  (provider) => ({
    ...provider,
    upstream_url_patterns: [],
    auth_template: {},
    required_org_credential_fields: [],
    setup_instructions: "",
    actions: [],
  })
);

interface CatalogStoryProps {
  kind: "mcp" | "external-app";
  state?:
    | "ready"
    | "loading"
    | "error"
    | "empty"
    | "installed-loading"
    | "installed-error";
}

function CatalogStory({ kind, state = "ready" }: CatalogStoryProps) {
  const [ready, setReady] = useState(false);
  const [cache] = useState(() => new Map<string, State>());
  useLayoutEffect(() => {
    const originalFetch = window.fetch;
    const json = (body: unknown, status = 200) =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
      });
    const mockFetch: typeof fetch = async (input, init) => {
      const path = new URL(
        input instanceof Request ? input.url : String(input),
        window.location.origin
      ).pathname;
      if (path === "/api/me")
        return json({
          id: "catalog-admin",
          email: "admin@example.com",
          is_active: true,
          is_verified: true,
          account_type: "basic",
          preferences: {},
          effective_permissions: [Permission.FULL_ADMIN_PANEL_ACCESS],
          admin_capabilities: [],
        });
      if (path === SWR_KEYS.buildExternalAppsBuiltInOptions) {
        if (state === "loading") return new Promise<Response>(() => {});
        if (state === "error") return json({ detail: "Unavailable" }, 503);
        return json(state === "empty" ? [] : descriptors);
      }
      if (path === SWR_KEYS.buildExternalAppsAdmin) {
        if (state === "installed-loading")
          return new Promise<Response>(() => {});
        if (state === "installed-error")
          return json({ detail: "Unavailable" }, 503);
        return json([]);
      }
      return originalFetch(input, init);
    };
    window.fetch = mockFetch;
    setReady(true);
    return () => {
      if (window.fetch === mockFetch) window.fetch = originalFetch;
    };
  }, [state]);
  return ready ? (
    <SWRConfig value={{ provider: () => cache, shouldRetryOnError: false }}>
      <UserProvider>
        <PluginAddCatalogModal
          catalogKind={kind}
          canManageActions
          installedEndpoints={new Set()}
          onClose={() => undefined}
          onPick={() => undefined}
        />
      </UserProvider>
    </SWRConfig>
  ) : null;
}

const meta = {
  title: "Plugins/Add catalog",
  component: CatalogStory,
  parameters: { layout: "fullscreen" },
} satisfies Meta<typeof CatalogStory>;

export default meta;
type Story = StoryObj<typeof meta>;
export const MCP: Story = { args: { kind: "mcp" } };
export const Apps: Story = { args: { kind: "external-app" } };
export const AppsLoading: Story = {
  args: { kind: "external-app", state: "loading" },
};
export const AppsError: Story = {
  args: { kind: "external-app", state: "error" },
};
export const AppsEmpty: Story = {
  args: { kind: "external-app", state: "empty" },
};
export const AppsInstalledLoading: Story = {
  args: { kind: "external-app", state: "installed-loading" },
};
export const AppsInstalledError: Story = {
  args: { kind: "external-app", state: "installed-error" },
};
