import { useEffect, useLayoutEffect, useState, type ReactNode } from "react";
import { SWRConfig, type State } from "swr";
import { Button, useCreateModal } from "@opal/components";
import { ToastProvider } from "@opal/layouts";
import { UserProvider } from "@/providers/UserProvider";
import MCPServerDetailPage from "@/sections/actions/MCPServerDetailPage";
import MCPServerSetupModal from "@/sections/actions/modals/MCPServerSetupModal";
import {
  MCPAuthenticationType,
  MCPAuthenticationPerformer,
  MCPOAuthProviderMode,
  MCPServerStatus,
  MCPTransportType,
  type MCPServer,
} from "@/lib/mcp/types";
import { deleteMCPServer } from "@/lib/mcp/svc";
import { Permission } from "@/lib/types";
import type { ToolSnapshot } from "@/lib/tools/types";
import type { EndpointPolicy } from "@/app/craft/v1/apps/registry";
import type { MCPOAuthDiscovery } from "@/lib/mcp/types";

export const storyServer: MCPServer = {
  id: 42,
  name: "Analytics MCP",
  description: "Query shared analytics with your workspace account.",
  server_url: "https://mcp.example.com/mcp",
  owner: "admin@example.com",
  transport: MCPTransportType.STREAMABLE_HTTP,
  auth_type: MCPAuthenticationType.OAUTH,
  auth_performer: MCPAuthenticationPerformer.PER_USER,
  oauth_provider_mode: MCPOAuthProviderMode.AUTO_DISCOVERY,
  admin_credentials: {},
  status: MCPServerStatus.CREATED,
  is_public: true,
  groups: [],
  users: [],
  tool_count: 3,
  available_in_craft: true,
  permissions: {
    edit: true,
    delete: true,
    authenticate: true,
    manage_status: true,
  },
};

export const storyTools: ToolSnapshot[] = [
  [
    "query_records",
    "Query records",
    "Search analytics records using a read-only query.",
  ],
  [
    "list_datasets",
    "List datasets",
    "List the datasets available to your account.",
  ],
  [
    "delete_records",
    "Delete records",
    "Permanently delete records from a dataset.",
  ],
].map(([name = "", display_name = "", description = ""], index) => ({
  id: index + 1,
  name,
  display_name,
  description,
  definition: null,
  custom_headers: [],
  in_code_tool_id: null,
  passthrough_auth: false,
  enabled: index !== 2,
  chat_selectable: true,
  agent_creation_selectable: true,
  default_enabled: false,
  mcp_server_id: 42,
  permissions: { toggle: true },
}));

export interface MCPStoryScenario {
  server?: MCPServer;
  edit?: boolean;
  defaultToolIds?: number[];
  wizard?: boolean;
  scoped?: boolean;
  community?: boolean;
  craftEnabled?: boolean;
  tools?: "loading" | "error" | "empty" | "read-only";
  toolsSave?: "pending" | "error";
  oauthEnabled?: boolean;
  groups?: "loading" | "error";
  load?: "loading" | "error";
  discovery?: MCPOAuthDiscovery["status"] | "unsupported" | "loading" | "retry";
  submit?: "pending" | "save-error" | "oauth-error" | "tools-error";
}

function pendingResponse(): Promise<Response> {
  return new Promise(() => {});
}
function json<T extends object>(data: T, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** Canvas-local fixtures; never fall through to a live API, including writes. */
function MockEnvironment({
  scenario,
  children,
}: {
  scenario: MCPStoryScenario;
  children: ReactNode;
}) {
  const [ready, setReady] = useState(false);
  const [cache] = useState(() => new Map<string, State>());
  useLayoutEffect(() => {
    const originalFetch = window.fetch;
    let probes = 0;
    let savedServer = scenario.server ?? storyServer;
    let defaultToolIds = scenario.defaultToolIds ?? [];
    let savedTools =
      scenario.tools === "empty"
        ? []
        : storyTools.map((tool) => ({
            ...tool,
            permissions: scenario.tools === "read-only" ? {} : tool.permissions,
          }));
    const mockFetch: typeof fetch = async (input, init) => {
      const path = new URL(
        input instanceof Request ? input.url : String(input),
        window.location.origin
      ).pathname;
      if (!path.startsWith("/api/")) return originalFetch(input, init);
      if (path === "/api/admin/default-assistant/configuration")
        return json({ tool_ids: defaultToolIds });
      if (path === "/api/admin/default-assistant" && init?.method === "PATCH") {
        const payload: unknown =
          typeof init.body === "string" ? JSON.parse(init.body) : null;
        if (
          payload &&
          typeof payload === "object" &&
          "tool_ids" in payload &&
          Array.isArray(payload.tool_ids)
        ) {
          defaultToolIds = payload.tool_ids.filter(
            (id): id is number => typeof id === "number"
          );
          return json({ tool_ids: defaultToolIds });
        }
        return json(
          { detail: "Invalid default assistant tool selection" },
          400
        );
      }
      if (path === "/api/admin/mcp/server/42" && init?.method === "DELETE")
        return json({});
      if (path === "/api/settings")
        return json({
          tier: scenario.community ? "community" : "business",
          ee_features_enabled: !scenario.community,
          onyx_craft_available: scenario.craftEnabled ?? false,
        });
      if (path === "/api/enterprise-settings") return json({});
      if (path === "/api/auth/type")
        return json({
          auth_type: "basic",
          oauth_enabled: scenario.oauthEnabled ?? true,
        });
      if (path === "/api/me")
        return json({
          id: "story-admin",
          email: "admin@example.com",
          is_active: true,
          is_superuser: false,
          is_verified: true,
          account_type: "basic",
          preferences: {},
          team_name: null,
          effective_permissions: scenario.scoped
            ? []
            : [Permission.FULL_ADMIN_PANEL_ACCESS, Permission.MANAGE_ACTIONS],
          admin_capabilities: [Permission.MANAGE_ACTIONS],
          is_group_manager: !!scenario.scoped,
        });
      if (path === "/api/manage/admin/user-group") {
        if (scenario.groups === "loading") return pendingResponse();
        if (scenario.groups === "error")
          return json(
            { detail: "Groups could not be loaded. Try again." },
            503
          );
        return json(
          Array.from({ length: 55 }, (_, index) => ({
            id: index + 1,
            name: `Team ${String(index + 1).padStart(2, "0")}`,
            users: [],
            manager_ids: ["story-admin"],
            cc_pairs: [],
            document_sets: [],
            personas: [],
            is_up_to_date: true,
            is_up_for_deletion: false,
            is_default: false,
            incognito_enabled: false,
          }))
        );
      }
      if (path === "/api/admin/mcp/servers/42") {
        if (scenario.load === "loading") return pendingResponse();
        if (scenario.load === "error")
          return json({ detail: "Saved settings could not be loaded." }, 503);
        return json(savedServer);
      }
      if (path === "/api/admin/mcp/oauth/discover") {
        probes += 1;
        if (scenario.discovery === "loading") return pendingResponse();
        const state =
          scenario.discovery === "retry"
            ? probes === 1
              ? "unreachable"
              : "metadata_found"
            : (scenario.discovery ?? "metadata_found");
        return json({
          status: state === "unsupported" ? "metadata_found" : state,
          supports_automatic_registration:
            state === "unsupported"
              ? false
              : state === "metadata_found"
                ? true
                : null,
          authorization_endpoint: "https://identity.example.com/authorize",
          token_endpoint: "https://identity.example.com/token",
        });
      }
      if (path === "/api/admin/mcp/oauth/connect") {
        if (scenario.submit === "oauth-error")
          return json(
            {
              oauth_error: "client_registration_failed",
              detail: "Provider registration failed.",
            },
            400
          );
        return json({
          status: "already_authenticated",
          server_id: 42,
          authorization_url: null,
          redirect_url: "/story-complete",
        });
      }
      if (path === "/api/admin/mcp/server/42/tools/snapshots") {
        if (scenario.tools === "loading") return pendingResponse();
        if (scenario.tools === "error")
          return json(
            { detail: "The server tools could not be loaded. Try again." },
            503
          );
        return json(savedTools);
      }
      if (path === "/api/admin/tool/status") {
        if (scenario.toolsSave === "pending") return pendingResponse();
        if (scenario.toolsSave === "error")
          return json(
            { detail: "Tool settings could not be saved. Try again." },
            503
          );
        const payload: unknown =
          typeof init?.body === "string" ? JSON.parse(init.body) : null;
        if (
          payload &&
          typeof payload === "object" &&
          "tool_ids" in payload &&
          Array.isArray(payload.tool_ids) &&
          "enabled" in payload &&
          typeof payload.enabled === "boolean"
        ) {
          const ids = payload.tool_ids.filter(
            (id): id is number => typeof id === "number"
          );
          const enabled = payload.enabled;
          savedTools = savedTools.map((tool) =>
            ids.includes(tool.id) ? { ...tool, enabled } : tool
          );
          return json({ updated_count: ids.length, tool_ids: ids });
        }
        return json({ detail: "Invalid tool status fixture payload" }, 400);
      }
      if (path.includes("/status")) return json({});
      if (
        path === "/api/admin/mcp/servers/create" ||
        path === "/api/admin/mcp/server" ||
        path === "/api/admin/mcp/server/42"
      ) {
        if (scenario.submit === "pending") return pendingResponse();
        if (scenario.submit === "save-error")
          return json(
            { detail: "The server configuration could not be saved." },
            503
          );
        const payload: unknown =
          typeof init?.body === "string" ? JSON.parse(init.body) : null;
        if (payload && typeof payload === "object") {
          if (
            "server_url" in payload &&
            typeof payload.server_url === "string" &&
            payload.server_url !== savedServer.server_url
          ) {
            savedServer = {
              ...savedServer,
              admin_credentials: {},
              auth_template: null,
              oauth_provider_mode: MCPOAuthProviderMode.AUTO_DISCOVERY,
              oauth_authorization_endpoint: undefined,
              oauth_token_endpoint: undefined,
            };
          }
          savedServer = { ...savedServer };
          if (
            "available_in_craft" in payload &&
            typeof payload.available_in_craft === "boolean"
          )
            savedServer.available_in_craft = payload.available_in_craft;
          if (
            "tool_policies" in payload &&
            payload.tool_policies &&
            typeof payload.tool_policies === "object"
          ) {
            const policies: Record<string, EndpointPolicy> = {};
            for (const [name, value] of Object.entries(payload.tool_policies)) {
              if (value === "ALWAYS" || value === "ASK" || value === "DENY")
                policies[name] = value;
            }
            savedServer.tool_policies = policies;
          }
          if ("name" in payload && typeof payload.name === "string")
            savedServer.name = payload.name;
          if ("server_url" in payload && typeof payload.server_url === "string")
            savedServer.server_url = payload.server_url;
          if (
            "description" in payload &&
            typeof payload.description === "string"
          )
            savedServer.description = payload.description;
        }
        return json({ ...savedServer, server_id: 42 });
      }
      return json({ detail: `No story fixture for ${path}` }, 404);
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
        dedupingInterval: 0,
      }}
    >
      <UserProvider>
        <ToastProvider>{children}</ToastProvider>
      </UserProvider>
    </SWRConfig>
  ) : null;
}

const REOPEN_PREVIEW = "Reopen preview";

function ModalCanvas({
  kind,
  scenario,
}: {
  kind: "auth" | "add" | "detail";
  scenario: MCPStoryScenario;
}) {
  const modal = useCreateModal();
  const [completed, setCompleted] = useState(false);
  useEffect(() => {
    modal.toggle(true);
  }, [modal.toggle]);
  if (kind === "detail" || completed)
    return <MCPServerDetailPage serverId={42} />;
  return (
    <>
      <div className="p-6">
        <Button
          onClick={() => {
            setCompleted(false);
            modal.toggle(true);
          }}
        >
          {REOPEN_PREVIEW}
        </Button>
      </div>
      <modal.Provider>
        <MCPServerSetupModal
          server={
            kind !== "add" || scenario.edit
              ? (scenario.server ?? storyServer)
              : null
          }
          initialPage={kind === "auth" ? "authentication" : "server"}
          editOnly={!scenario.wizard && (kind === "auth" || !!scenario.edit)}
          onCompleted={() => setCompleted(true)}
          onDelete={async () => {
            await deleteMCPServer(42);
          }}
          onTriggerFetchTools={async () => {
            if (scenario.submit === "tools-error")
              throw new Error(
                "Tools could not be loaded. Check the server and try again."
              );
          }}
        />
      </modal.Provider>
    </>
  );
}

export function MCPModalStory({
  kind,
  scenario,
}: {
  kind: "auth" | "add" | "detail";
  scenario: MCPStoryScenario;
}) {
  return (
    <MockEnvironment scenario={scenario}>
      <ModalCanvas kind={kind} scenario={scenario} />
    </MockEnvironment>
  );
}
