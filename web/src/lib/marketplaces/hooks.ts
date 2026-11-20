"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import useSWR, { useSWRConfig } from "swr";
import { toast } from "@opal/layouts";
import { errorHandlingFetcher, skipRetryOnAuthError } from "@/lib/fetcher";
import type {
  MarketplaceDetail,
  MarketplaceList,
  MarketplaceSummary,
} from "@/lib/marketplaces/types";
import { marketplaceSyncState } from "@/lib/marketplaces/utils";
import { useRefreshSkillLists } from "@/lib/skills/hooks";
import { SWR_KEYS } from "@/lib/swr-keys";

const POLL_MS = 3000;
// A started sync clears its request mark, so keep reading for a while after
// the user asks for one.
const FOLLOW_MS = 60_000;

function useFollow() {
  const until = useRef(0);
  const [, setTick] = useState(0);
  return {
    following: () => Date.now() < until.current,
    follow: () => {
      until.current = Date.now() + FOLLOW_MS;
      setTick((tick) => tick + 1);
    },
  };
}

function syncKey(marketplace: MarketplaceSummary): string {
  return [
    marketplace.last_synced_at,
    marketplace.last_synced_revision,
    marketplace.plugin_count,
    marketplace.needs_confirmation,
  ].join("|");
}

export function useMarketplaces(enabled = true) {
  const { following, follow } = useFollow();
  const refreshSkillLists = useRefreshSkillLists();
  const { data, error, isLoading, mutate } = useSWR<MarketplaceList, Error>(
    enabled ? SWR_KEYS.marketplaces : null,
    errorHandlingFetcher,
    {
      refreshInterval: (latest) =>
        following() ||
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
    follow,
  };
}

export function useMarketplace(marketplaceId: string | null) {
  const { following, follow } = useFollow();
  const { data, error, isLoading, mutate } = useSWR<MarketplaceDetail, Error>(
    marketplaceId ? SWR_KEYS.marketplace(marketplaceId) : null,
    errorHandlingFetcher,
    {
      refreshInterval: (latest) =>
        following() ||
        (latest !== undefined && marketplaceSyncState(latest) === "syncing")
          ? POLL_MS
          : 0,
      onErrorRetry: skipRetryOnAuthError,
    }
  );
  return { marketplace: data, error, isLoading, refresh: mutate, follow };
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
