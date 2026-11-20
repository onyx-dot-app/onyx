"use client";

import { useEffect, useRef } from "react";
import { useFormatter, useTranslations } from "next-intl";
import useSWR, { useSWRConfig } from "swr";
import { toast } from "@opal/layouts";
import {
  errorHandlingFetcher,
  FetchError,
  fetchErrorDetail,
  skipRetryOnAuthError,
} from "@/lib/fetcher";
import type {
  MarketplaceDetail,
  MarketplaceList,
  MarketplaceReasonCode,
  MarketplaceSummary,
} from "@/lib/marketplaces/types";
import {
  EXTERNAL_REPOSITORY_LIMIT,
  isExternalRepositoryLimit,
  marketplaceSyncState,
} from "@/lib/marketplaces/utils";
import { useRefreshSkillLists } from "@/lib/skills/hooks";
import { SWR_KEYS } from "@/lib/swr-keys";

const POLL_MS = 3000;

function syncKey(marketplace: MarketplaceSummary): string {
  return [
    marketplace.last_synced_at,
    marketplace.last_synced_revision,
    marketplace.plugin_count,
  ].join("|");
}

export function useMarketplaces(enabled = true) {
  const refreshSkillLists = useRefreshSkillLists();
  const { data, error, isLoading, mutate } = useSWR<MarketplaceList, Error>(
    enabled ? SWR_KEYS.marketplaces : null,
    errorHandlingFetcher,
    {
      refreshInterval: (latest) =>
        latest?.marketplaces.some(
          (row) => marketplaceSyncState(row) === "syncing"
        )
          ? POLL_MS
          : 0,
      onErrorRetry: skipRetryOnAuthError,
    }
  );
  const seen = useRef<Map<string, string> | null>(null);
  useEffect(() => {
    if (!data) return;
    const next = new Map(
      data.marketplaces.map((row) => [row.id, syncKey(row)])
    );
    const before = seen.current;
    seen.current = next;
    if (
      before &&
      (before.size !== next.size ||
        Array.from(next).some(([id, key]) => before.get(id) !== key))
    )
      refreshSkillLists();
  }, [data, refreshSkillLists]);
  return {
    marketplaces: data?.marketplaces,
    error,
    isLoading,
    refresh: mutate,
  };
}

export function useMarketplace(marketplaceId: string | null) {
  const { data, error, isLoading, mutate } = useSWR<MarketplaceDetail, Error>(
    marketplaceId ? SWR_KEYS.marketplace(marketplaceId) : null,
    errorHandlingFetcher,
    {
      refreshInterval: (latest) =>
        latest !== undefined && marketplaceSyncState(latest) === "syncing"
          ? POLL_MS
          : 0,
      onErrorRetry: skipRetryOnAuthError,
    }
  );
  return { marketplace: data, error, isLoading, refresh: mutate };
}

export function useMarketplaceAdded(): (
  marketplace: MarketplaceDetail
) => void {
  const t = useTranslations("plugins.marketplaces.add");
  const { mutate } = useSWRConfig();
  return (marketplace) => {
    toast.success(t("added", { name: marketplace.name }));
    void mutate(SWR_KEYS.marketplaces);
  };
}

export interface MarketplaceCopy {
  /** The translated reason of an entry, else the server's text. */
  entryReason: (entry: {
    reason: string | null;
    reason_code: MarketplaceReasonCode | null;
  }) => string | null;
  /** The once-per-marketplace note for entries past the external limit. */
  limitNote: (
    entries: readonly { reason_code: MarketplaceReasonCode | null }[]
  ) => string | null;
  /** A preview, add or sync error: GitHub's limit with its reset time is
   * translated, other errors keep the server's detail. */
  describeError: (error: unknown, fallback: string) => string;
}

export function useMarketplaceCopy(): MarketplaceCopy {
  const t = useTranslations("plugins.marketplaces");
  const format = useFormatter();
  return {
    entryReason: (entry) => {
      if (entry.reason_code === null) return entry.reason;
      if (isExternalRepositoryLimit(entry.reason_code))
        return t("reason.pastLimit");
      return t(`reason.${entry.reason_code}`);
    },
    limitNote: (entries) => {
      const code = entries
        .map((entry) => entry.reason_code)
        .find(isExternalRepositoryLimit);
      if (code === undefined) return null;
      return t(`reason.${code}`, { limit: EXTERNAL_REPOSITORY_LIMIT[code] });
    },
    describeError: (error, fallback) => {
      const info = error instanceof FetchError ? error.info : null;
      if (info?.error_code === "RATE_LIMITED") {
        const resetAt = "reset_at" in info ? info.reset_at : null;
        return typeof resetAt === "string"
          ? t("errors.rateLimitedUntil", {
              time: format.dateTime(new Date(resetAt), { timeStyle: "short" }),
            })
          : t("errors.rateLimited");
      }
      return fetchErrorDetail(error) ?? fallback;
    },
  };
}
