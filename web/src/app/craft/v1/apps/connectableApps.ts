import type { IconFunctionComponent } from "@opal/types";
import {
  ExternalAppUserResponse,
  getAppTypeLogo,
} from "@/app/craft/v1/apps/registry";
import {
  disconnectUserFromApp,
  startExternalAppOAuth,
  upsertUserCredentials,
} from "@/app/craft/services/externalAppsService";
import {
  disconnectMCPServer,
  saveMCPUserCredentials,
  startMCPUserOAuth,
} from "@/lib/tools/mcpService";
import {
  MCPAuthenticationPerformer,
  MCPAuthenticationType,
  MCPServer,
} from "@/lib/tools/interfaces";
import { getActionIcon } from "@/lib/tools/mcpUtils";
import { CRAFT_APPS_PATH } from "@/app/craft/v1/constants";

// Normalized view of anything connectable on the Apps page — external apps and
// craft-enabled MCP servers render through the same card so users see one
// uniform "Apps" surface.
export interface ConnectableApp {
  key: string;
  name: string;
  description: string;
  /** Deep-link (`?connect=`) target — the external app's id; null for MCP. */
  connectId: string | null;
  authenticated: boolean;
  logo: IconFunctionComponent;
  /** How the user connects; null = nothing for the user to do (org-managed). */
  connectMode: "oauth" | "credentials" | null;
  credentialKeys: string[];
  credentialValues: Record<string, string>;
  /** Returns the URL to redirect to for OAuth. */
  startOAuth: () => Promise<string>;
  saveCredentials: (values: Record<string, string>) => Promise<void>;
  /** Absent when there is no per-user credential to remove. */
  disconnect: (() => Promise<void>) | null;
}

export function externalAppToConnectable(
  app: ExternalAppUserResponse
): ConnectableApp {
  return {
    key: `app-${app.id}`,
    name: app.name,
    description: app.supports_oauth
      ? "Connect with OAuth"
      : "Connect with credentials",
    connectId: String(app.id),
    authenticated: app.authenticated,
    logo: getAppTypeLogo(app.app_type),
    connectMode: app.supports_oauth ? "oauth" : "credentials",
    credentialKeys: app.credential_keys,
    credentialValues: app.credential_values,
    startOAuth: async () => (await startExternalAppOAuth(app.id)).authorize_url,
    saveCredentials: (values) => upsertUserCredentials(app.id, values),
    disconnect: () => disconnectUserFromApp(app.id),
  };
}

export function mcpServerToConnectable(
  server: MCPServer
): ConnectableApp | null {
  // Pass-through OAuth authenticates via the user's Onyx login token at runtime:
  // always usable, with nothing for the user to connect or disconnect. Its
  // per-user `user_authenticated` is false (no stored config), so it must not
  // drive the regular OAuth flow or the connected state.
  const passThrough = server.auth_type === MCPAuthenticationType.PT_OAUTH;
  const perUser =
    !passThrough &&
    server.auth_performer === MCPAuthenticationPerformer.PER_USER &&
    server.auth_type !== MCPAuthenticationType.NONE;
  const authenticated =
    passThrough ||
    (server.user_authenticated ?? server.is_authenticated ?? false);
  // Org-managed (admin-performed / no-auth) servers with nothing configured
  // aren't actionable for the user — hide rather than show a dead card.
  if (!perUser && !authenticated) return null;
  const credentialKeys: string[] = server.auth_template?.required_fields?.length
    ? server.auth_template.required_fields
    : ["api_key"];
  return {
    key: `mcp-${server.id}`,
    name: server.name,
    description: server.description ?? "",
    connectId: null,
    authenticated,
    logo: getActionIcon(server.server_url, server.name),
    connectMode: !perUser
      ? null
      : server.auth_type === MCPAuthenticationType.API_TOKEN
        ? "credentials"
        : "oauth",
    credentialKeys,
    credentialValues: server.user_credentials ?? {},
    startOAuth: async () =>
      (await startMCPUserOAuth(server.id, CRAFT_APPS_PATH)).oauth_url,
    saveCredentials: (values) =>
      saveMCPUserCredentials(server.id, values, server.transport),
    disconnect: perUser ? () => disconnectMCPServer(server.id) : null,
  };
}
