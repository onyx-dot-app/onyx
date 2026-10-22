"use client";

import { useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import useSWR from "swr";
import { Card, MessageCard, Text, Tooltip } from "@opal/components";
import { Section } from "@opal/layouts";
import { CardLoader } from "@opal/loaders";
import type { RichStr } from "@opal/types";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type {
  CCPairThroughputWindow,
  IndexingOverviewResponse,
} from "@/lib/connectors/types";
import {
  THROUGHPUT_POLL_MS,
  ThroughputBars,
  ThroughputWindowPicker,
  type SliceRange,
} from "@/views/admin/connectors/ConnectorDetailPage/ThroughputChart";

const WINDOWS: readonly CCPairThroughputWindow[] = ["1h", "24h", "7d"];

const BARS_HEIGHT = 120;

interface StatProps {
  value: number;
  /** The total `value` is part of, such as the active pairs for the indexing ones. */
  whole?: number;
  caption: string | RichStr;
  label: string | RichStr;
  /** Explains the figure on hover. */
  tooltip?: string;
}
/** A figure, over its total when it has one, above a two-line label. */
function Stat({ value, whole, caption, label, tooltip }: StatProps) {
  const t = useTranslations("admin.indexing.overview");
  const format = useFormatter();
  return (
    <Tooltip tooltip={tooltip} side="top">
      <Section
        alignItems="start"
        justifyContent="start"
        gap={1}
        padding={2}
        width="auto"
        height="fit"
        className="min-w-32"
      >
        <Section
          flexDirection="row"
          justifyContent="start"
          alignItems="end"
          gap={0}
          width="fit"
          height="fit"
        >
          <Text font="main-ui-action" color="text-04">
            {format.number(value)}
          </Text>
          {whole !== undefined && (
            <Text font="main-ui-body" color="text-04">
              {t("ratio.whole", { whole: format.number(whole) })}
            </Text>
          )}
        </Section>
        <Section alignItems="start" gap={0} width="fit" height="fit">
          <Text font="secondary-body" color="text-03">
            {caption}
          </Text>
          <Text font="secondary-body" color="text-03">
            {label}
          </Text>
        </Section>
      </Section>
    </Tooltip>
  );
}

export interface OverviewCardProps {
  /** The span of the chart the page is narrowed to. A new window clears it. */
  range: SliceRange | null;
  onRangeChange: (range: SliceRange | null) => void;
}

/** Every readable connector at a glance: how many index now, the documents they hold, and documents indexed over time. */
export default function OverviewCard({
  range,
  onRangeChange,
}: OverviewCardProps) {
  const t = useTranslations("admin.indexing.overview");
  const [timeWindow, setTimeWindow] = useState<CCPairThroughputWindow>("1h");
  const { data, error } = useSWR<IndexingOverviewResponse>(
    SWR_KEYS.indexMonitoringOverview(timeWindow),
    errorHandlingFetcher,
    // A window switch changes the key, so the loader shows until the new window lands.
    { refreshInterval: THROUGHPUT_POLL_MS }
  );
  // The span belongs to the old chart, so a new window drops it.
  function changeWindow(picked: CCPairThroughputWindow) {
    setTimeWindow(picked);
    onRangeChange(null);
  }
  if (error !== undefined) {
    return <MessageCard variant="error" title={t("loadError")} />;
  }
  if (data === undefined) return <CardLoader descriptionLines={3} />;

  return (
    // Fills the row beside the Activities card, so the two cards share one height.
    <Card
      border="solid"
      rounding={4}
      padding={2}
      height="full"
      data-testid="indexing-overview"
    >
      <Section alignItems="stretch" gap={1} height="fit">
        <Section
          flexDirection="row"
          alignItems="start"
          justifyContent="start"
          gap={1}
          height="fit"
          wrap
        >
          <Stat
            value={data.indexing_connectors}
            whole={data.active_connectors}
            caption={t("connectors.caption")}
            label={t("connectors.label")}
          />
          <Stat
            value={data.total_docs_indexed}
            caption={t("documents.caption")}
            label={t("documents.label")}
            tooltip={t("documents.tooltip")}
          />
          <Stat
            value={data.recent_docs_indexed}
            caption={t("processed.caption")}
            label={t("processed.label")}
            tooltip={t("processed.tooltip")}
          />
          <Section
            flexDirection="row"
            justifyContent="end"
            alignItems="center"
            gap={1}
            width="auto"
            height="fit"
            className="grow basis-0"
            wrap
          >
            <ThroughputWindowPicker
              windows={WINDOWS}
              value={timeWindow}
              onChange={changeWindow}
              selection={range}
              onClearSelection={() => onRangeChange(null)}
            />
          </Section>
        </Section>
        <Section padding={2} alignItems="stretch" height="fit">
          <ThroughputBars
            data={data.throughput}
            range={timeWindow}
            height={BARS_HEIGHT}
            selection={range}
            onRangeSelect={onRangeChange}
          />
        </Section>
      </Section>
    </Card>
  );
}
