"use client";

import { useLocale, useTranslations } from "next-intl";
import { Card, CopyButton, ProgressBar, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import ColumnLabels from "@/views/admin/ServiceStatusPage/ColumnLabels";
import { SvgAlertTriangle } from "@opal/icons";
import { useClusterStatus } from "@/lib/service-status/hooks";
import type {
  ClusterNodeStatus,
  UsageThresholds,
} from "@/lib/service-status/types";
import {
  barColor,
  diskPercent,
  toSize,
  vectorPercent,
} from "@/views/admin/ServiceStatusPage/format";

// OpenSearch names a node after its host when no name is set: a container
// or instance hash, which means nothing to an admin.
const GENERATED_NAME = /^[0-9a-f]{12,}$/i;

interface UsageCellProps {
  label: string;
  value: number;
  used: number;
  total: number;
  warning: number;
  critical: number;
}

function UsageCell({
  label,
  value,
  used,
  total,
  warning,
  critical,
}: UsageCellProps) {
  const t = useTranslations("admin.serviceStatus.nodes");
  const locale = useLocale();
  return (
    <Section gap={0.25} alignItems="stretch" width="full">
      <Section flexDirection="row" gap={0.25} alignItems="center" width="fit">
        <Text as="p" font="main-ui-action" color="text-04">
          {t("percent", { value: Math.round(value) })}
        </Text>
        {value >= critical && (
          <SvgAlertTriangle size={14} className="text-status-error-05" />
        )}
      </Section>
      <Text as="p" font="secondary-body" color="text-03">
        {t("usedOfTotal", {
          used: toSize(used, locale, total).value,
          total: toSize(total, locale).value,
          unit: toSize(total, locale).unit,
        })}
      </Text>
      <ProgressBar
        value={value}
        max={100}
        color={barColor(value, warning, critical)}
        aria-label={label}
      />
    </Section>
  );
}

interface NodeRowsProps {
  nodes: ClusterNodeStatus[];
  thresholds: UsageThresholds;
}

function NodeRows({ nodes, thresholds }: NodeRowsProps) {
  const t = useTranslations("admin.serviceStatus.nodes");
  return (
    <Section gap={3} alignItems="stretch" width="full">
      <ColumnLabels title={t("title")} labels={[t("disk"), t("vector")]} />
      <Section gap={2} alignItems="stretch" width="full">
        {nodes.map((node, index) => (
          <Card
            key={node.node_id}
            border="solid"
            rounding={4}
            padding={3}
            data-testid="service-status-node"
          >
            <Section
              flexDirection="row"
              gap={2}
              alignItems="start"
              width="full"
            >
              <Section gap={0.25} alignItems="start" width="full">
                <Section
                  flexDirection="row"
                  gap={0}
                  alignItems="center"
                  width="fit"
                >
                  <Text as="p" font="main-ui-action" color="text-04">
                    {GENERATED_NAME.test(node.name)
                      ? t("unnamed", { number: index + 1 })
                      : node.name}
                  </Text>
                  <CopyButton
                    getCopyText={() => node.name}
                    tooltip={t("copyName", { name: node.name })}
                    size="xs"
                  />
                </Section>
                <Text as="p" font="secondary-body" color="text-03">
                  {t("shards", { count: node.shard_count })}
                </Text>
              </Section>
              <UsageCell
                label={t("disk")}
                value={diskPercent(node)}
                used={node.disk_used_bytes}
                total={node.disk_total_bytes}
                warning={thresholds.disk_warning_percent}
                critical={thresholds.disk_critical_percent}
              />
              <UsageCell
                label={t("vector")}
                value={vectorPercent(node)}
                used={node.vector_bytes}
                total={node.file_cache_bytes}
                warning={thresholds.vector_warning_percent}
                critical={thresholds.vector_critical_percent}
              />
            </Section>
          </Card>
        ))}
      </Section>
    </Section>
  );
}

export default function DataNodesList() {
  const { data } = useClusterStatus();
  // The page shows the loader until the first read.
  return data ? (
    <NodeRows nodes={data.nodes} thresholds={data.thresholds} />
  ) : null;
}
