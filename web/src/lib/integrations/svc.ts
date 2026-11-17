import { parseErrorDetail } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type {
  AdminIntegrationDetail,
  InstallationPolicy,
  IntegrationActionsResponse,
  IntegrationActionsUpdate,
  IntegrationCreate,
  IntegrationOAuthCallbackResult,
  IntegrationStatus,
  IntegrationUpdate,
  MemberActionPolicies,
  MemberPluginState,
  PluginAccessUpdate,
  PluginAccessView,
} from "@/lib/integrations/types";

type RequestBody =
  | IntegrationCreate
  | IntegrationUpdate
  | IntegrationActionsUpdate
  | { fields: Record<string, string> }
  | { organization: boolean; return_path: string }
  | { installation_policy: InstallationPolicy }
  | { enabled: boolean }
  | PluginAccessUpdate
  | { code: string; state: string }
  | { actions: Record<string, "allow" | null> };

async function request(
  url: string,
  method: "POST" | "PATCH" | "PUT" | "DELETE",
  body?: RequestBody
): Promise<Response> {
  const res = await fetch(url, {
    method,
    headers:
      body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(
      await parseErrorDetail(res, `Request failed (${res.status})`)
    );
  }
  return res;
}

export async function createIntegration(
  body: IntegrationCreate
): Promise<AdminIntegrationDetail> {
  const res = await request(SWR_KEYS.adminIntegrations, "POST", body);
  return res.json();
}

export async function updateIntegration(
  id: number,
  body: IntegrationUpdate
): Promise<AdminIntegrationDetail> {
  const res = await request(SWR_KEYS.adminIntegration(id), "PATCH", body);
  return res.json();
}

export async function deleteIntegration(id: number): Promise<void> {
  await request(SWR_KEYS.adminIntegration(id), "DELETE");
}

export async function updateIntegrationActions(
  id: number,
  body: IntegrationActionsUpdate
): Promise<IntegrationActionsResponse> {
  const res = await request(SWR_KEYS.adminIntegrationActions(id), "PUT", body);
  return res.json();
}

export async function refreshIntegrationActions(
  id: number
): Promise<IntegrationActionsResponse> {
  const res = await request(
    `${SWR_KEYS.adminIntegrationActions(id)}/refresh`,
    "POST"
  );
  return res.json();
}

export async function saveOrganizationConnection(
  id: number,
  fields: Record<string, string>
): Promise<IntegrationStatus> {
  const res = await request(
    `${SWR_KEYS.adminIntegration(id)}/organization-connection`,
    "PUT",
    { fields }
  );
  return res.json();
}

export async function deleteOrganizationConnection(
  id: number
): Promise<IntegrationStatus> {
  const res = await request(
    `${SWR_KEYS.adminIntegration(id)}/organization-connection`,
    "DELETE"
  );
  return res.json();
}

async function startOAuth(
  id: number,
  organization: boolean,
  returnPath: string
): Promise<string> {
  const res = await request(`/api/integrations/${id}/oauth/start`, "POST", {
    organization,
    return_path: returnPath,
  });
  const body: { authorization_url: string } = await res.json();
  return body.authorization_url;
}

export async function setPluginInstallationPolicy(
  pluginId: string,
  installationPolicy: InstallationPolicy
): Promise<void> {
  await request(SWR_KEYS.adminPluginInstallationPolicy(pluginId), "PUT", {
    installation_policy: installationPolicy,
  });
}

export function startOrganizationOAuth(
  id: number,
  returnPath: string
): Promise<string> {
  return startOAuth(id, true, returnPath);
}

export function startUserOAuth(
  id: number,
  returnPath: string
): Promise<string> {
  return startOAuth(id, false, returnPath);
}

export async function saveUserConnection(
  id: number,
  fields: Record<string, string>
): Promise<IntegrationStatus> {
  const res = await request(
    `${SWR_KEYS.integrations}/${id}/connection`,
    "PUT",
    {
      fields,
    }
  );
  return res.json();
}

export async function deleteUserConnection(
  id: number
): Promise<IntegrationStatus> {
  const res = await request(
    `${SWR_KEYS.integrations}/${id}/connection`,
    "DELETE"
  );
  return res.json();
}

/** Exchanges the code of an OAuth callback. The code is single-use. */
export async function completeIntegrationOAuth(
  code: string,
  state: string
): Promise<IntegrationOAuthCallbackResult> {
  const res = await request(`${SWR_KEYS.integrations}/oauth/callback`, "POST", {
    code,
    state,
  });
  return res.json();
}

/** Saves the user's "Always allow" choices: "allow" saves one, null clears it. */
export async function saveAlwaysAllow(
  id: number,
  actions: Record<string, "allow" | null>
): Promise<MemberActionPolicies> {
  const res = await request(SWR_KEYS.integrationActionPolicies(id), "PUT", {
    actions,
  });
  return res.json();
}

/** The user's on/off switch of a plugin that holds only integrations. */
export async function setPluginEnabled(
  pluginId: string,
  enabled: boolean
): Promise<MemberPluginState> {
  const res = await request(`${SWR_KEYS.plugin(pluginId)}/enabled`, "PUT", {
    enabled,
  });
  return res.json();
}

export async function updatePluginAccess(
  pluginId: string,
  body: PluginAccessUpdate
): Promise<PluginAccessView> {
  const res = await request(SWR_KEYS.pluginAccess(pluginId), "PUT", body);
  return res.json();
}

/** Moves a private plugin to the Organization library. */
export async function publishPlugin(pluginId: string): Promise<void> {
  await request(`${SWR_KEYS.plugin(pluginId)}/publish`, "POST");
}
