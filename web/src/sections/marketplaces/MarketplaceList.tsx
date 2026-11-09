"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import useSWR from "swr";
import { Button, Card, OnyxLoader, Text } from "@opal/components";
import { IllustrationContent, Section } from "@opal/layouts";
import type { RichStr } from "@opal/types";
import { listMarketplaces } from "@/lib/marketplaces/api";
import type { Marketplace } from "@/lib/marketplaces/types";
import {
  fetchErrorDetail,
  isAuthStatusError,
  skipRetryOnAuthError,
} from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import MarketplaceSummary from "@/sections/marketplaces/MarketplaceSummary";
import MarketplaceDetailDialog from "@/sections/marketplaces/MarketplaceDetailDialog";

export interface MarketplaceListProps {
  /** Disable reads and polling when the host tab is not shown. */
  visible?: boolean;
  /** Filter shared source rows using kind data the host actually has. */
  filter?: (marketplace: Marketplace) => boolean;
  /** Defaults to API skill counts. Return null when a kind has no count data. */
  getCountLabel?: (marketplace: Marketplace) => string | RichStr | null;
  onSyncFromGitHub?: () => void;
  onChanged?: () => void;
  onConfigureAccess?: (marketplace: Marketplace) => void;
}

export default function MarketplaceList({
  visible = true,
  filter,
  getCountLabel,
  onSyncFromGitHub,
  onChanged,
  onConfigureAccess,
}: MarketplaceListProps) {
  const t = useTranslations("marketplaces");
  const [selected, setSelected] = useState<string | null>(null);
  const previous = useRef<Marketplace[] | undefined>(undefined);
  const { data, error, mutate } = useSWR(
    visible ? SWR_KEYS.marketplaces : null,
    listMarketplaces,
    {
      refreshInterval: (rows) =>
        visible && rows?.some((row) => row.sync_pending) ? 3000 : 0,
      refreshWhenHidden: false,
      onErrorRetry: skipRetryOnAuthError,
      errorRetryCount: 2,
    }
  );
  useEffect(() => {
    if (!visible || !data) return;
    const before = previous.current;
    previous.current = data;
    if (!before) return;
    const oldRows = new Map(before.map((row) => [row.id, row]));
    if (
      before.some((row) => !data.some((next) => next.id === row.id)) ||
      data.some((row) => {
        const old = oldRows.get(row.id);
        if (!old) return row.live_skill_count > 0;
        return (
          (old.sync_pending && !row.sync_pending) ||
          old.last_synced_at !== row.last_synced_at ||
          old.last_synced_revision !== row.last_synced_revision ||
          old.live_skill_count !== row.live_skill_count ||
          old.retired_skill_count !== row.retired_skill_count
        );
      })
    )
      onChanged?.();
  }, [data, visible, onChanged]);
  if (!visible) return null;
  const rows = filter ? data?.filter(filter) : data;
  return (
    <Section height="auto" alignItems="stretch" gap={3}>
      <Section
        height="auto"
        flexDirection="row"
        justifyContent="between"
        wrap
        gap={2}
      >
        <Text as="h2" font="heading-section">
          {t("listTitle")}
        </Text>
        {onSyncFromGitHub && (
          <Button prominence="secondary" onClick={onSyncFromGitHub}>
            {t("syncTitle")}
          </Button>
        )}
      </Section>
      {error ? (
        <>
          <IllustrationContent
            title={t(isAuthStatusError(error) ? "unauthorized" : "loadError")}
            description={fetchErrorDetail(error) ?? undefined}
          />
          <Button prominence="secondary" onClick={() => void mutate()}>
            {t("retry")}
          </Button>
        </>
      ) : !rows ? (
        <OnyxLoader />
      ) : rows.length === 0 ? (
        <IllustrationContent
          title={t("emptyList")}
          description={t("emptyListDescription")}
        />
      ) : (
        rows.map((row) => (
          <Card key={row.id} border="solid" padding={3}>
            <Section height="auto" alignItems="stretch" gap={3}>
              <MarketplaceSummary
                marketplace={row}
                countLabel={getCountLabel?.(row)}
              />
              <Section height="auto" flexDirection="row" justifyContent="end">
                <Button
                  prominence="secondary"
                  aria-label={t("detailsFor", { name: row.name })}
                  onClick={() => setSelected(row.id)}
                >
                  {t("details")}
                </Button>
              </Section>
            </Section>
          </Card>
        ))
      )}
      {selected && (
        <MarketplaceDetailDialog
          open
          marketplaceId={selected}
          onClose={() => setSelected(null)}
          onChanged={onChanged}
          onConfigureAccess={
            onConfigureAccess
              ? (row) => {
                  setSelected(null);
                  onConfigureAccess(row);
                }
              : undefined
          }
          getCountLabel={getCountLabel}
        />
      )}
    </Section>
  );
}
