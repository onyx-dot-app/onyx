import { SWR_KEYS } from "@/lib/swr-keys";
import {
  SSOProviderCreateRequest,
  SSOProviderResponse,
  SSOProviderUpdateRequest,
} from "@/lib/sso/interfaces";

async function errorDetail(response: Response): Promise<string> {
  try {
    return (await response.json()).detail ?? "Request failed";
  } catch {
    return "Request failed";
  }
}

export async function createSSOProvider(
  request: SSOProviderCreateRequest
): Promise<SSOProviderResponse> {
  const response = await fetch(SWR_KEYS.adminSsoProviders, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) throw new Error(await errorDetail(response));
  return response.json();
}

export async function updateSSOProvider(
  providerId: number,
  request: SSOProviderUpdateRequest
): Promise<SSOProviderResponse> {
  const response = await fetch(`${SWR_KEYS.adminSsoProviders}/${providerId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) throw new Error(await errorDetail(response));
  return response.json();
}

export async function setSSOProviderEnabled(
  providerId: number,
  enabled: boolean
): Promise<SSOProviderResponse> {
  const response = await fetch(
    `${SWR_KEYS.adminSsoProviders}/${providerId}/enabled`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    }
  );
  if (!response.ok) throw new Error(await errorDetail(response));
  return response.json();
}
