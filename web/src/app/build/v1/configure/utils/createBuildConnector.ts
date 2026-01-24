import { ValidSources } from "@/lib/types";
import { Credential } from "@/lib/connectors/credentials";
import { createConnector } from "@/lib/connector";
import { linkCredential } from "@/lib/credential";
import { connectorConfigs, isLoadState } from "@/lib/connectors/connectors";

export interface CreateBuildConnectorParams {
  connectorType: ValidSources;
  credential: Credential<any>;
  connectorSpecificConfig?: Record<string, any>;
  connectorName?: string;
  userEmail?: string;
}

export interface CreateBuildConnectorResult {
  success: boolean;
  error?: string;
  connectorId?: number;
}

function getUserIdentifier(email?: string): string {
  if (!email) return "";
  // Extract the part before @ and sanitize it
  const prefix = email.split("@")[0] || email;
  // Replace any non-alphanumeric characters with dashes
  return `-${prefix.replace(/[^a-zA-Z0-9]/g, "-")}`;
}

export async function createBuildConnector({
  connectorType,
  credential,
  connectorSpecificConfig = {},
  connectorName,
  userEmail,
}: CreateBuildConnectorParams): Promise<CreateBuildConnectorResult> {
  const config =
    connectorConfigs[connectorType as keyof typeof connectorConfigs];
  const userIdentifier = getUserIdentifier(userEmail);
  const name = connectorName || `build-mode-${connectorType}${userIdentifier}`;

  const filteredConfig: Record<string, any> = {};
  Object.entries(connectorSpecificConfig).forEach(([key, value]) => {
    if (value !== "" && value !== null && value !== undefined) {
      if (Array.isArray(value) && value.length === 0) {
        return;
      }
      filteredConfig[key] = value;
    }
  });

  try {
    const [connectorError, connector] = await createConnector({
      name,
      source: connectorType,
      input_type: isLoadState(connectorType) ? "load_state" : "poll",
      connector_specific_config: filteredConfig,
      refresh_freq: config?.overrideDefaultFreq || 1800,
      prune_freq: 2592000,
      indexing_start: null,
      access_type: "private",
      groups: [],
    });

    if (connectorError || !connector) {
      return {
        success: false,
        error: connectorError || "Failed to create connector",
      };
    }

    const linkResponse = await linkCredential(
      connector.id,
      credential.id,
      name,
      "private",
      [],
      undefined,
      "file_system"
    );

    if (!linkResponse.ok) {
      const linkError = await linkResponse.json();
      return {
        success: false,
        error: linkError.detail || "Failed to link credential",
      };
    }

    return {
      success: true,
      connectorId: connector.id,
    };
  } catch (err) {
    return {
      success: false,
      error: err instanceof Error ? err.message : "Failed to create connector",
    };
  }
}
