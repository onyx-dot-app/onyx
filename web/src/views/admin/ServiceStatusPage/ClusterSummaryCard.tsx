"use client";

import type { RichStr } from "@opal/types";
import { useFormatter, useLocale, useNow, useTranslations } from "next-intl";
import { Badge, Card, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { SvgAlertCircle, SvgAlertTriangle, SvgCheckCircle } from "@opal/icons";
import type { ClusterHealth, ClusterStatus } from "@/lib/service-status/types";
import { useClusterStatus } from "@/lib/service-status/hooks";
import { compactParts, toSize } from "@/views/admin/ServiceStatusPage/format";
import ValueWithUnit from "@/views/admin/ServiceStatusPage/ValueWithUnit";

const HEALTH_ICONS = {
  green: SvgCheckCircle,
  yellow: SvgAlertCircle,
  red: SvgAlertTriangle,
} as const;

const HEALTH_TOOLTIP_KEYS = {
  green: "healthGreen",
  yellow: "healthYellow",
  red: "healthRed",
} as const;

const HEALTH_COLORS = {
  green: "success",
  yellow: "warning",
  red: "error",
} as const;

interface StatProps {
  label: string | RichStr;
  value: string;
  unit?: string;
}

function Stat({ label, value, unit }: StatProps) {
  return (
    <Section gap={0.25} alignItems="start" width="full">
      <Text as="p" font="secondary-body" color="text-03">
        {label}
      </Text>
      <ValueWithUnit value={value} unit={unit} size="headline" />
    </Section>
  );
}

interface ClusterSummaryProps {
  status: ClusterStatus;
}

function ClusterSummary({ status }: ClusterSummaryProps) {
  const t = useTranslations("admin.serviceStatus.cluster");
  const format = useFormatter();
  const locale = useLocale();
  const now = useNow({ updateInterval: 15_000 });
  const health: ClusterHealth = status.health;
  // On one data node replicas can never be placed, so yellow is the normal
  // state there and the badge looks healthy; its tooltip says why.
  const singleNodeYellow = health === "yellow" && status.data_node_count === 1;
  const badgeHealth: ClusterHealth = singleNodeYellow ? "green" : health;
  const chunks = status.indexes
    .filter((index) => index.is_current)
    .reduce((sum, index) => sum + index.chunk_count, 0);
  // The index serving search; a reindex target has its own row below.
  const indexBytes = status.indexes
    .filter((index) => index.is_current)
    .reduce((sum, index) => sum + index.store_size_bytes, 0);
  const current = status.indexes.find((index) => index.is_current);
  const copies = current ? current.replicas + 1 : 0;

  return (
    <Card border="solid" rounding={4} padding={4}>
      <Section flexDirection="row" gap={2} alignItems="start" width="full">
        <Section gap={0.5} alignItems="start" width="full">
          <Text as="p" font="secondary-action" color="text-04">
            {t("status")}
          </Text>
          <Badge
            title={
              status.version
                ? t("version", { version: status.version })
                : t("health", { health })
            }
            icon={HEALTH_ICONS[badgeHealth]}
            color={HEALTH_COLORS[badgeHealth]}
            size={6}
            tooltip={t(
              singleNodeYellow
                ? "healthYellowSingleNode"
                : HEALTH_TOOLTIP_KEYS[health]
            )}
          />
          <Text as="p" font="secondary-body" color="text-03">
            {t("updated", {
              // A server clock slightly ahead must not read "in 1 second".
              time: format.relativeTime(
                new Date(
                  Math.min(Date.parse(status.checked_at), now.getTime())
                ),
                now
              ),
            })}
          </Text>
        </Section>
        <Section gap={1} alignItems="start" width="full">
          <Stat label={t("dataNodes")} value={String(status.data_node_count)} />
          <Stat
            label={t("shards")}
            value={t("shardLayout", {
              primaries: current?.primary_shards ?? status.primary_shards,
              copies,
            })}
            unit={t("copies")}
          />
        </Section>
        <Section gap={1} alignItems="start" width="full">
          <Stat
            label={t("indexSize")}
            value={toSize(indexBytes, locale).value}
            unit={toSize(indexBytes, locale).unit}
          />
          <Stat
            label={t("chunks")}
            value={compactParts(chunks, locale)[0]}
            unit={compactParts(chunks, locale)[1]}
          />
        </Section>
      </Section>
    </Card>
  );
}

export default function ClusterSummaryCard() {
  const { data } = useClusterStatus();
  // The page shows the loader until the first read.
  return data ? <ClusterSummary status={data} /> : null;
}
