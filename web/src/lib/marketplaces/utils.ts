import type {
  MarketplaceDefaultPolicy,
  MarketplaceSummary,
  MarketplaceSyncState,
} from "@/lib/marketplaces/types";

export const MARKETPLACE_DEFAULT_POLICIES = [
  "AVAILABLE",
  "DEFAULT",
  "REQUIRED",
  "NOT_AVAILABLE",
] as const satisfies readonly MarketplaceDefaultPolicy[];

export function isMarketplaceDefaultPolicy(
  value: string
): value is MarketplaceDefaultPolicy {
  return MARKETPLACE_DEFAULT_POLICIES.some((policy) => policy === value);
}

export function marketplaceSyncState(
  marketplace: MarketplaceSummary
): MarketplaceSyncState {
  if (marketplace.syncing) return "syncing";
  if (marketplace.last_error) return "failed";
  if (marketplace.last_synced_at === null) return "not_synced";
  return "synced";
}

export function marketplaceSource(marketplace: MarketplaceSummary): string {
  return [
    marketplace.repository,
    marketplace.folder ? `/${marketplace.folder}` : "",
    marketplace.ref ? `@${marketplace.ref}` : "",
  ].join("");
}
