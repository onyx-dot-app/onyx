import { parseErrorDetail } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type {
  AdminIntegrationDetail,
  IntegrationActionsResponse,
  IntegrationActionsUpdate,
  IntegrationCreate,
  IntegrationStatus,
  IntegrationUpdate,
} from "@/lib/integrations/types";

type RequestBody =
  | IntegrationCreate
  | IntegrationUpdate
  | IntegrationActionsUpdate
  | { fields: Record<string, string> }
  | { organization: boolean; return_path: string };

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

export async function startOrganizationOAuth(
  id: number,
  returnPath: string
): Promise<string> {
  const res = await request(`/api/integrations/${id}/oauth/start`, "POST", {
    organization: true,
    return_path: returnPath,
  });
  const body: { authorization_url: string } = await res.json();
  return body.authorization_url;
}
