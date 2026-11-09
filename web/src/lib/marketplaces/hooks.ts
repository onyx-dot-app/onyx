"use client";

import { useState } from "react";
import { useSWRConfig } from "swr";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { useSettings } from "@/lib/settings/hooks";
import { SWR_KEYS } from "@/lib/swr-keys";
import { Tier } from "@/lib/tiers/types";
import { Permission } from "@/lib/types";
import type {
  Marketplace,
  MarketplaceAccessUpdate,
} from "@/lib/marketplaces/types";

export type MarketplaceAccessDraft = Required<MarketplaceAccessUpdate> & {
  public_permission: NonNullable<Marketplace["public_permission"]> | null;
};

export const DEFAULT_COMPANY_MARKETPLACE_ACCESS: MarketplaceAccessDraft = {
  public_permission: "VIEWER",
  installation_policy: "AVAILABLE",
  group_shares: [],
};

export function marketplaceAccessDraft(
  marketplace: Marketplace
): MarketplaceAccessDraft {
  return {
    public_permission: marketplace.public_permission ?? null,
    installation_policy: marketplace.installation_policy,
    group_shares: marketplace.group_shares.map(
      ({ user_group_id, ...share }) => ({
        ...share,
        group_id: user_group_id,
      })
    ),
  };
}

/** Mount once per dialog session; later snapshots must not replace edits. */
export function useCompanyMarketplaceAccess(initial: MarketplaceAccessDraft) {
  const [draft, setDraft] = useState(initial);
  const settings = useSettings();
  const { isGlobalHolder } = usePermissionAuthority(Permission.MANAGE_SKILLS);
  const { mutate } = useSWRConfig();
  const status = !isGlobalHolder
    ? "forbidden"
    : settings.error
      ? "error"
      : settings.isLoading
        ? "loading"
        : settings.tier === undefined
          ? "error"
          : settings.tier === Tier.COMMUNITY
            ? "community"
            : "paid";
  const ready =
    status === "paid" ||
    (status === "community" &&
      draft.public_permission === "VIEWER" &&
      draft.group_shares.length === 0);

  function refreshSettings() {
    void mutate(SWR_KEYS.settings);
    void mutate(SWR_KEYS.enterpriseSettings);
  }

  return { draft, setDraft, status, ready, refreshSettings };
}
