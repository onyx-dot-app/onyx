import {
  EXTERNAL_APP_TYPES,
  type ExternalAppType,
} from "@/app/craft/v1/apps/registry";
import type { MemberIntegration } from "@/lib/integrations/types";

/** An app integration of a plugin that the user has turned on. */
export interface CraftApp {
  /** The external app id that Craft cards and skills name. */
  id: number;
  integration_id: number;
  name: string;
  app_type: ExternalAppType;
  authenticated: boolean;
  /** OAuth apps connect in a new tab; others through the credential form. */
  supports_oauth: boolean;
}

/** An MCP integration of a plugin that the user has turned on. */
export interface CraftMcpServer {
  /** The MCP server id. */
  id: number;
  name: string;
  server_url: string;
  /** Whether Craft can authenticate this user against the server. */
  craft_connected: boolean;
}

function appType(presetId: string | null): ExternalAppType {
  return EXTERNAL_APP_TYPES.find((type) => type === presetId) ?? "CUSTOM";
}

function turnedOn(integration: MemberIntegration): boolean {
  return integration.plugins.some((plugin) => plugin.enabled);
}

export function toCraftApps(integrations: MemberIntegration[]): CraftApp[] {
  return integrations.flatMap((integration) =>
    integration.external_app_id !== null && turnedOn(integration)
      ? [
          {
            id: integration.external_app_id,
            integration_id: integration.id,
            name: integration.name,
            app_type: appType(integration.preset_id),
            authenticated: integration.status.state === "connected",
            supports_oauth: integration.auth_method === "oauth2",
          },
        ]
      : []
  );
}

export function toCraftMcpServers(
  integrations: MemberIntegration[]
): CraftMcpServer[] {
  return integrations.flatMap((integration) =>
    integration.mcp_server_id !== null &&
    integration.server_url !== null &&
    turnedOn(integration)
      ? [
          {
            id: integration.mcp_server_id,
            name: integration.name,
            server_url: integration.server_url,
            craft_connected: integration.status.state === "connected",
          },
        ]
      : []
  );
}
