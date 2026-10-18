import { createOAuthConfig, updateOAuthConfig } from "@/lib/oauth/api";
import {
  MASKED_OAUTH_CREDENTIAL,
  oauthConfigRequest,
} from "@/lib/oauth/config";
import { updateCustomTool } from "@/lib/plugins/openapi/svc";
import type { ToolSnapshot } from "@/lib/tools/types";
import type { OpenAPIAuthFormValues } from "@/lib/plugins/openapi/types";

export async function saveOpenApiAuthentication({
  tool,
  values,
  pendingOAuthConfigId,
  onOAuthConfigCreated,
}: {
  tool: ToolSnapshot;
  values: OpenAPIAuthFormValues;
  pendingOAuthConfigId?: number | null;
  onOAuthConfigCreated?: (id: number) => void;
}): Promise<void> {
  let payload: Parameters<typeof updateCustomTool>[1];

  switch (values.authMethod) {
    case "none":
      payload = {
        custom_headers: [],
        passthrough_auth: false,
        oauth_config_id: null,
      };
      break;
    case "oauth": {
      let oauthConfigId = tool.oauth_config_id ?? pendingOAuthConfigId;
      const config = oauthConfigRequest(values, Boolean(oauthConfigId));
      if (oauthConfigId) {
        await updateOAuthConfig(oauthConfigId, {
          ...config,
          client_id: config.client_id || undefined,
          client_secret: config.client_secret || undefined,
        });
      } else {
        if (
          !config.client_id ||
          !config.client_secret ||
          config.client_id === MASKED_OAUTH_CREDENTIAL ||
          config.client_secret === MASKED_OAUTH_CREDENTIAL
        )
          throw new Error();
        const createdConfig = await createOAuthConfig({
          name: `${tool.name} OAuth`,
          ...config,
        });
        oauthConfigId = createdConfig.id;
        onOAuthConfigCreated?.(createdConfig.id);
      }
      payload = {
        custom_headers: [],
        passthrough_auth: false,
        oauth_config_id: oauthConfigId,
      };
      break;
    }
    case "custom-header":
      payload = {
        custom_headers: values.headers
          .map(({ key, value }) => ({ key: key.trim(), value: value.trim() }))
          .filter(({ key, value }) => key && value),
        passthrough_auth: false,
        oauth_config_id: null,
      };
      break;
    case "pt-oauth":
      payload = {
        custom_headers: [],
        passthrough_auth: true,
        oauth_config_id: null,
      };
      break;
    default: {
      const exhaustive: never = values.authMethod;
      throw new Error(exhaustive);
    }
  }

  const response = await updateCustomTool(tool.id, payload);
  if (response.error || !response.data) {
    throw new Error(response.error ?? "");
  }
}
