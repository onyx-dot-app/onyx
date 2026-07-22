import { SWR_KEYS } from "@/lib/swr-keys";
import {
  SSOProviderCreateRequest,
  SSOProviderResponse,
  SSOProviderUpdateRequest,
} from "@/lib/sso/interfaces";

const JSON_HEADERS = { "Content-Type": "application/json" };

async function errorDetail(response: Response): Promise<string> {
  try {
    return (await response.json()).detail ?? "Request failed";
  } catch {
    return "Request failed";
  }
}

async function ssoRequest<T>(
  url: string,
  method: string,
  body: unknown
): Promise<T> {
  const response = await fetch(url, {
    method,
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(await errorDetail(response));
  return response.json();
}

export function createSSOProvider(
  request: SSOProviderCreateRequest
): Promise<SSOProviderResponse> {
  return ssoRequest<SSOProviderResponse>(
    SWR_KEYS.adminSsoProviders,
    "POST",
    request
  );
}

export function updateSSOProvider(
  providerId: number,
  request: SSOProviderUpdateRequest
): Promise<SSOProviderResponse> {
  return ssoRequest<SSOProviderResponse>(
    `${SWR_KEYS.adminSsoProviders}/${providerId}`,
    "PATCH",
    request
  );
}

export function setSSOProviderEnabled(
  providerId: number,
  enabled: boolean
): Promise<SSOProviderResponse> {
  return ssoRequest<SSOProviderResponse>(
    `${SWR_KEYS.adminSsoProviders}/${providerId}/enabled`,
    "POST",
    { enabled }
  );
}
