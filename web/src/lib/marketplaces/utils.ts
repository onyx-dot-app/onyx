import type {
  MarketplaceDefaultPolicy,
  MarketplaceEntryStatus,
  MarketplaceReasonCode,
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

/** Mirrors `REMOTE_REPOSITORY_MAX_COUNT*` in skills/marketplace/provider.py. */
export const EXTERNAL_REPOSITORY_LIMIT = {
  external_repository_limit: 200,
  external_repository_limit_without_login: 20,
} as const;

export function isExternalRepositoryLimit(
  code: MarketplaceReasonCode | null
): code is keyof typeof EXTERNAL_REPOSITORY_LIMIT {
  return code !== null && code in EXTERNAL_REPOSITORY_LIMIT;
}

/** Ready first, then blocked, then not supported; by key inside each. */
const STATUS_ORDER: Record<MarketplaceEntryStatus, number> = {
  ok: 0,
  blocked: 1,
  not_supported: 2,
};

export function sortMarketplaceEntries<
  T extends { key: string; status: MarketplaceEntryStatus },
>(entries: readonly T[], locale: string): T[] {
  return [...entries].sort(
    (a, b) =>
      STATUS_ORDER[a.status] - STATUS_ORDER[b.status] ||
      a.key.localeCompare(b.key, locale)
  );
}
