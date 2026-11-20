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

const STATE_COLOR = {
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
    <Section
      flexDirection="row"
      justifyContent="start"
      gap={1}
      height="auto"
      width="auto"
    >
      <Badge title={t(`state.${state}`)} color={STATE_COLOR[state]} />
      <Text font="secondary-body" color="text-03" maxLines={1} overflowTooltip>
        {state === "failed" && marketplace.last_error
          ? marketplace.last_error
          : lastSync(marketplace)}
      </Text>
    </Section>
  );
}
