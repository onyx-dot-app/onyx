"use client";

import { useFormatter, useTranslations } from "next-intl";
import { Badge, MessageCard, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import type { RichStr } from "@opal/types";
import {
  marketplaceSourceSchema,
  type Marketplace,
} from "@/lib/marketplaces/types";

export interface MarketplaceSummaryProps {
  marketplace: Marketplace;
  /** Undefined shows API skill counts; null hides counts. Never infer plugin counts. */
  countLabel?: string | RichStr | null;
}

export default function MarketplaceSummary({
  marketplace: row,
  countLabel,
}: MarketplaceSummaryProps) {
  const t = useTranslations("marketplaces");
  const format = useFormatter();
  const source = marketplaceSourceSchema.validateSync(
    {
      provider: row.provider,
      provider_config: row.provider_config,
      personal: !!row.owner_user_id,
    },
    { strict: true }
  );
  const status = row.sync_pending ? "pending" : (row.sync_status ?? "idle");
  const counts =
    countLabel === undefined
      ? t("skillCounts", {
          live: row.live_skill_count,
          retired: row.retired_skill_count,
        })
      : countLabel;
  return (
    <Section height="auto" alignItems="stretch" gap={2}>
      <Section
        height="auto"
        flexDirection="row"
        justifyContent="between"
        wrap
        gap={2}
      >
        <Text font="main-ui-action" wordWrap="wrap-anywhere">
          {row.name}
        </Text>
        <Section
          height="auto"
          width="fit"
          flexDirection="row"
          gap={1}
          wrap
          className="max-w-full"
        >
          <Badge title={t(row.owner_user_id ? "personalScope" : "company")} />
          <Badge
            color={
              status === "applied"
                ? "success"
                : status === "failed"
                  ? "error"
                  : status === "needs_confirmation"
                    ? "warning"
                    : "default"
            }
            title={t(status)}
          />
        </Section>
      </Section>
      <Text font="secondary-mono" wordWrap="wrap-anywhere">
        {t("source", {
          owner: source.provider_config.owner,
          repo: source.provider_config.repo,
          ref: source.provider_config.ref,
        })}
      </Text>
      <Text font="secondary-body" wordWrap="wrap-anywhere">
        {t("folderValue", {
          folder: source.provider_config.folder || t("rootFolder"),
        })}
      </Text>
      {counts !== null && <Text font="secondary-body">{counts}</Text>}
      {row.last_synced_revision && (
        <Text font="secondary-mono" wordWrap="wrap-anywhere">
          {t("revision", { revision: row.last_synced_revision })}
        </Text>
      )}
      {row.last_synced_at && (
        <Text font="secondary-body">
          {t("lastSynced", {
            date: format.dateTime(new Date(row.last_synced_at), {
              dateStyle: "medium",
              timeStyle: "short",
            }),
          })}
        </Text>
      )}
      {row.last_error && (
        <MessageCard
          outerPadding={1}
          innerPadding={1}
          variant="error"
          title={row.last_error}
        />
      )}
    </Section>
  );
}
