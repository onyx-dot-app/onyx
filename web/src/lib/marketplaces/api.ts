import { errorHandlingFetchWith } from "@/lib/fetcher";
import type {
  MarketplaceCreateRequest,
  MarketplaceDefaultPolicy,
  MarketplaceDetail,
  MarketplacePreview,
  MarketplaceSource,
} from "@/lib/marketplaces/types";
import { SWR_KEYS } from "@/lib/swr-keys";

type MarketplacePostBody = MarketplaceSource | MarketplaceCreateRequest;

function post<T>(url: string, body?: MarketplacePostBody): Promise<T> {
  return errorHandlingFetchWith<T>(
    url,
    body === undefined
      ? { method: "POST" }
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }
  );
}

export function previewMarketplace(
  source: MarketplaceSource
): Promise<MarketplacePreview> {
  return post(`${SWR_KEYS.marketplaces}/preview`, source);
}

export function createMarketplace(
  request: MarketplaceCreateRequest
): Promise<MarketplaceDetail> {
  return post(SWR_KEYS.marketplaces, request);
}

export function syncMarketplace(
  marketplaceId: string
): Promise<MarketplaceDetail> {
  return post(`${SWR_KEYS.marketplace(marketplaceId)}/sync`);
}

export function replaceMarketplaceLogin(
  marketplaceId: string
): Promise<MarketplaceDetail> {
  return post(`${SWR_KEYS.marketplace(marketplaceId)}/replace-login`);
}

export function setMarketplaceDefaultAccess(
  marketplaceId: string,
  installationPolicy: MarketplaceDefaultPolicy
): Promise<MarketplaceDetail> {
  return errorHandlingFetchWith(
    `${SWR_KEYS.marketplace(marketplaceId)}/default-access`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ installation_policy: installationPolicy }),
    }
  );
}

export async function deleteMarketplace(marketplaceId: string): Promise<void> {
  await errorHandlingFetchWith<null>(SWR_KEYS.marketplace(marketplaceId), {
    method: "DELETE",
  });
}
