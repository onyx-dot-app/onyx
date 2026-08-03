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

/** Which system a connectable came from. Surfaced to the user: the two are
 * connected and governed differently, so a row must never be ambiguous. */
export type ConnectableKind = "app" | "mcp";

/** Query param selecting the Apps page tab. Exported so deep-link producers
 * (e.g. the input-bar picker) and the page can't disagree on the contract. */
export const CRAFT_APPS_TAB_PARAM = "tab";

export function parseConnectableTab(value: string | null): ConnectableKind {
  return value === "mcp" ? "mcp" : "app";
}

// Normalized view of anything connectable on the Apps page — external apps and
// craft-enabled MCP servers render through the same card, distinguished by
// `kind` rather than by which id field happens to be set.
export interface ConnectableApp {
  key: string;
  kind: ConnectableKind;
  name: string;
  description: string;
  /** External app identity; null for MCP servers. */
  externalAppId: number | null;
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
    kind: "app",
    name: app.name,
    description: app.supports_oauth
      ? "Connect with OAuth"
      : "Connect with credentials",
    externalAppId: app.id,
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

export function mcpServerToConnectable(server: MCPServer): ConnectableApp {
  // Pass-through OAuth authenticates via the user's Onyx login token at runtime,
  // so there is nothing for the user to connect or disconnect. That says nothing
  // about whether it works for them — a password-login user has no login OAuth
  // token, and `craft_connected` reports that.
  const passThrough = server.auth_type === MCPAuthenticationType.PT_OAUTH;
  const perUser =
    !passThrough &&
    server.auth_performer === MCPAuthenticationPerformer.PER_USER &&
    server.auth_type !== MCPAuthenticationType.NONE;
  // The backend's craft-emission predicate, not "a config row exists" — the
  // page must not claim connected for a server Craft drops from the session.
  const authenticated = server.craft_connected ?? false;
  const credentialKeys: string[] = server.auth_template?.required_fields?.length
    ? server.auth_template.required_fields
    : ["api_key"];
  return {
    key: `mcp-${server.id}`,
    kind: "mcp",
    name: server.name,
    description: server.description ?? "",
    externalAppId: null,
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
