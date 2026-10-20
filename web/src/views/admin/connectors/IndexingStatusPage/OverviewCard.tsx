"use client";

import { useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import useSWR from "swr";
import { Card, MessageCard, Text } from "@opal/components";
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

const WINDOWS: readonly CCPairThroughputWindow[] = ["1h", "12h", "24h", "7d"];

const BARS_HEIGHT = 120;

interface RatioStatProps {
  part: number;
  whole: number;
  caption: string | RichStr;
  label: string | RichStr;
}
/** A figure against its total over a two-line label, such as the indexing pairs over the active ones. */
function RatioStat({ part, whole, caption, label }: RatioStatProps) {
  const t = useTranslations("admin.indexing.overview");
  const format = useFormatter();
  return (
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
          {format.number(part)}
        </Text>
        <Text font="main-ui-body" color="text-04">
          {t("ratio.whole", { whole: format.number(whole) })}
        </Text>
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
          <RatioStat
            part={data.indexing_connectors}
            whole={data.active_connectors}
            caption={t("connectors.caption")}
            label={t("connectors.label")}
          />
          <RatioStat
            part={data.recent_docs_indexed}
            whole={data.total_docs_indexed}
            caption={t("documents.caption")}
            label={t("documents.label")}
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
