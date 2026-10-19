import { useLayoutEffect, useState } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { userEvent, within } from "storybook/test";
import { SWRConfig, type State } from "swr";
import { ToastProvider } from "@opal/layouts";
import type { ToolSnapshot } from "@/lib/tools/types";
import { extractMethodSpecsFromDefinition } from "@/lib/tools/utils";
import OpenAPIPluginModal from "@/views/admin/PluginsPage/OpenAPIPluginModal";
import messages from "@/i18n/messages/en.json";

const tool: ToolSnapshot = {
  id: 42,
  name: "Release API",
  display_name: "Release API",
  description: "Read release status and schedule deployments.",
  definition: {
    openapi: "3.0.0",
    info: {
      title: "Release API",
      version: "1.0",
      description: "Read release status and schedule deployments.",
    },
    servers: [{ url: "https://releases.example.com" }],
    paths: {
      "/releases": {
        get: {
          operationId: "listReleases",
          summary: "List recent releases and their status.",
          responses: { "200": { description: "Releases" } },
        },
      },
      "/deployments": {
        post: {
          operationId: "scheduleDeployment",
          summary: "Schedule a deployment for a release.",
          responses: { "200": { description: "Deployment" } },
        },
      },
      "/deployments/{deploymentId}": {
        delete: {
          operationId: "cancelDeployment",
          summary: "Cancel a deployment that has not started.",
          responses: { "200": { description: "Cancelled" } },
        },
      },
    },
  },
  custom_headers: [{ key: "Authorization", value: "********" }],
  in_code_tool_id: null,
  passthrough_auth: false,
  enabled: true,
  chat_selectable: true,
  agent_creation_selectable: true,
  default_enabled: false,
  permissions: { edit: true, authenticate: true, toggle: true, delete: true },
};

interface OpenAPIPluginStoryProps {
  scenario?: "ready" | "read-only" | "loading" | "error" | "missing";
}

function OpenAPIPluginStory({ scenario = "ready" }: OpenAPIPluginStoryProps) {
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
      if (!path.startsWith("/api/")) return originalFetch(input, init);
      if (path === "/api/settings")
        return json({ ee_features_enabled: false, tier: "community" });
      if (path === "/api/auth/type")
        return json({ auth_type: "basic", oauth_enabled: true });
      if (path === "/api/enterprise-settings") return json({});
      if (path === "/api/tool/openapi") {
        if (scenario === "loading") return new Promise<Response>(() => {});
        if (scenario === "error")
          return json({ detail: "Plugins are unavailable" }, 503);
        return json(
          scenario === "missing"
            ? []
            : [
                {
                  ...tool,
                  permissions: scenario === "read-only" ? {} : tool.permissions,
                },
              ]
        );
      }
      if (path === "/api/admin/tool/custom/validate")
        return json({
          methods: extractMethodSpecsFromDefinition(tool.definition),
        });
      if (path.startsWith("/api/admin/tool/")) return json(tool);
      return json({ detail: "No story fixture" }, 404);
    };
    window.fetch = mockFetch;
    setReady(true);
    return () => {
      if (window.fetch === mockFetch) window.fetch = originalFetch;
    };
  }, [scenario]);

  return ready ? (
    <SWRConfig
      value={{
        provider: () => cache,
        shouldRetryOnError: false,
        revalidateOnFocus: false,
      }}
    >
      <ToastProvider>
        <div className="h-screen bg-background-tint-01">
          <OpenAPIPluginModal toolId={42} />
        </div>
      </ToastProvider>
    </SWRConfig>
  ) : null;
}

const meta = {
  title: "Apps/Plugins/OpenAPI plugin details",
  component: OpenAPIPluginStory,
  parameters: { layout: "fullscreen" },
} satisfies Meta<typeof OpenAPIPluginStory>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Ready: Story = {};
export const ReadOnly: Story = { args: { scenario: "read-only" } };
export const Loading: Story = { args: { scenario: "loading" } };
export const LoadError: Story = { args: { scenario: "error" } };
export const Missing: Story = { args: { scenario: "missing" } };
export const EditDetails: Story = {
  name: "Plugin details",
  play: async () => {
    await userEvent.click(
      await within(document.body).findByRole("tab", {
        name: messages.actions.plugins.openapi.detailsTitle,
      })
    );
  },
};
export const EditSchema: Story = {
  name: "Schema",
  play: async () => {
    await userEvent.click(
      await within(document.body).findByRole("tab", {
        name: messages.actions.plugins.openapi.schemaTitle,
      })
    );
  },
};
export const Authentication: Story = {
  play: async () => {
    await userEvent.click(
      await within(document.body).findByRole("tab", {
        name: messages.actions.mcpDetail.authentication,
      })
    );
  },
};

export const Tools: Story = {
  play: async () => {
    await userEvent.click(
      await within(document.body).findByRole("tab", {
        name: messages.actions.mcpTools.title,
      })
    );
  },
};
