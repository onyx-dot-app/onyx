"use client";

import { useFormatter, useTranslations } from "next-intl";
import { Badge, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import type { StatusColor } from "@opal/types";
import { marketplaceSyncState } from "@/lib/marketplaces/utils";
import type {
  MarketplaceSummary,
  MarketplaceSyncState,
} from "@/lib/marketplaces/types";

export const SYNC_STATE_COLOR = {
  syncing: "pending",
  failed: "error",
  not_synced: "default",
  synced: "success",
} as const satisfies Record<MarketplaceSyncState, StatusColor>;

export function useLastSyncCopy(
  prefixed = true
): (marketplace: MarketplaceSummary) => string {
  const t = useTranslations("plugins.marketplaces.sync");
  const format = useFormatter();
  return (marketplace) => {
    if (!marketplace.last_synced_at) return t("never");
    const date = format.dateTime(new Date(marketplace.last_synced_at), {
      dateStyle: "medium",
      timeStyle: "short",
    });
    return prefixed ? t("lastSync", { date }) : date;
  };
}

interface MarketplaceSyncStatusProps {
  marketplace: MarketplaceSummary;
}

export default function MarketplaceSyncStatus({
  marketplace,
}: MarketplaceSyncStatusProps) {
  const t = useTranslations("plugins.marketplaces.sync");
  const lastSync = useLastSyncCopy();
  const state = marketplaceSyncState(marketplace);
  return (
    <Section flexDirection="row" justifyContent="start" gap={1} height="auto">
      <Badge title={t(`state.${state}`)} color={SYNC_STATE_COLOR[state]} />
      {/* grow lets the text shrink to the cell and wrap instead of widening it. */}
      <Section grow={1} height="auto" alignItems="start">
        <Text
          font="secondary-body"
          color="text-03"
          maxLines={2}
          overflowTooltip
        >
          {state === "failed" && marketplace.last_error
            ? marketplace.last_error
            : lastSync(marketplace)}
        </Text>
      </Section>
    </Section>
  );
}
