import type {
  MarketplaceDefaultPolicy,
  MarketplaceSummary,
  MarketplaceSyncState,
} from "@/lib/marketplaces/types";

export const MARKETPLACE_DEFAULT_POLICIES = [
  "AVAILABLE",
  "DEFAULT",
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
  if (marketplace.sync_requested) return "syncing";
  if (marketplace.needs_confirmation) return "needs_confirmation";
  if (marketplace.last_error) return "failed";
  if (marketplace.last_synced_at === null) return "syncing";
  return "synced";
}

/** "owner/repo/folder@ref": the GitHub place a marketplace reads. */
export function marketplaceSource(marketplace: MarketplaceSummary): string {
  return [
    marketplace.repository,
    marketplace.folder ? `/${marketplace.folder}` : "",
    marketplace.ref ? `@${marketplace.ref}` : "",
  ].join("");
}
