import { SWR_KEYS } from "@/lib/swr-keys";
import type { SSOProviderOption, SSOProviderType } from "@/lib/auth/types";
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

// The backend serves snake_case, so the wire shape is spelled out separately
// from the camelCase model rather than cast across the boundary.
interface SSOProviderOptionWire {
  name: string;
  display_name: string;
  provider_type: SSOProviderType;
  authorize_url: string;
}

export async function discoverSSOProviders(
  email: string
): Promise<SSOProviderOption[]> {
  const data = await ssoRequest<{ providers?: SSOProviderOptionWire[] }>(
    "/api/auth/sso/discover",
    "POST",
    { email }
  );
  return (data.providers ?? []).map((provider) => ({
    name: provider.name,
    displayName: provider.display_name,
    providerType: provider.provider_type,
    authorizeUrl: provider.authorize_url,
  }));
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

export interface SSOLoginDomainStatus {
  domain: string;
  verified: boolean;
  // Whether the provider holding this domain is saved. Verifying needs a saved
  // claim, so the record shows first and verifying unlocks on save.
  claimed: boolean;
  // The TXT record to publish. Unset once the domain is verified.
  record_host?: string | null;
  record_value?: string | null;
}

export interface SSOLoginDomains {
  domains: SSOLoginDomainStatus[];
}

export function fetchDomainRecords(
  domains: string[]
): Promise<SSOLoginDomains> {
  return ssoRequest<SSOLoginDomains>(
    `${SWR_KEYS.adminSsoDomains}/records`,
    "POST",
    { domains }
  );
}

export function verifyDomainViaDns(domain: string): Promise<SSOLoginDomains> {
  return ssoRequest<SSOLoginDomains>(
    `${SWR_KEYS.adminSsoDomains}/verify-dns`,
    "POST",
    { domain }
  );
}
