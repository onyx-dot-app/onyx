"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Card, MessageCard, SelectButton } from "@opal/components";
import { Section } from "@opal/layouts";
import { LineLoader } from "@opal/loaders";
import { SvgPanelRight } from "@opal/icons";
import { cn } from "@opal/utils";
import type { RichStr } from "@opal/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import type {
  CCPairThroughputWindow,
  IndexingOverviewResponse,
} from "@/lib/connectors/types";
import {
  ThroughputBars,
  ThroughputWindowPicker,
  type SliceRange,
  type ThroughputActivityLinks,
} from "@/views/admin/connectors/ConnectorDetailPage/ThroughputChart";
import { useThroughputData } from "@/lib/connectors/hooks";
import LineLayout, {
  LineFigure,
} from "@/views/admin/connectors/shared/LineLayout";
import { BESIDE } from "@/views/admin/connectors/shared/PanelPageBody";

const WINDOWS: readonly CCPairThroughputWindow[] = ["1h", "24h", "7d"];

const BARS_HEIGHT = 120;

export interface OverviewCardProps {
  /** The span of the chart the page is narrowed to. A new window clears it. */
  range: SliceRange | null;
  onRangeChange: (range: SliceRange | null) => void;
  /** Ties the chart to the page's activity panel. */
  activityLinks?: ThroughputActivityLinks;
  panelOpen: boolean;
  onPanelOpenChange: (open: boolean) => void;
  className?: string;
}

/** The fleet's counts card with the Activities panel button, over the graph card with the window picker and chart. Both are stat lines, so their figures start over the connector rows' columns. */
export default function OverviewCard({
  range,
  onRangeChange,
  activityLinks,
  panelOpen,
  onPanelOpenChange,
  className,
}: OverviewCardProps) {
  const t = useTranslations("admin.indexing.overview");
  const tStats = useTranslations("admin.connector.statusCard.documents");
  const tPanel = useTranslations("admin.indexing.activities.panelButton");
  const [timeWindow, setTimeWindow] = useState<CCPairThroughputWindow>("1h");
  const { ref, data, error, stale } =
    useThroughputData<IndexingOverviewResponse>((bins, tzOffsetMinutes) =>
      SWR_KEYS.indexMonitoringOverview(timeWindow, bins, tzOffsetMinutes)
    );
  // The span belongs to the old chart, so a new window drops it.
  function changeWindow(picked: CCPairThroughputWindow) {
    setTimeWindow(picked);
    onRangeChange(null);
  }
  const panelLabel = tPanel(panelOpen ? "hide" : "show");
  const paused = data?.paused_connectors;
  // After a load error the figures show dashes, even over a kept earlier response, and the message in the graph card's place explains them.
  const failed = error !== undefined;
  function figure(value: number | undefined, label: string | RichStr) {
    if (failed) return <LineFigure value={null} label={label} />;
    if (value !== undefined) return <LineFigure value={value} label={label} />;
    return <LineLoader lines={2} />;
  }

  return (
    <Section
      alignItems="stretch"
      gap={2}
      height="fit"
      className={className}
      data-testid="indexing-overview"
    >
      <Card border="solid" rounding={4} padding={2}>
        <LineLayout
          variant="stat"
          a={figure(data?.active_connectors, t("activeConnectors"))}
          b={figure(data?.total_docs_indexed, tStats("totalLabel"))}
          c={
            paused === undefined ? null : (
              <LineFigure
                value={failed ? null : paused}
                label={t("pausedConnectors")}
              />
            )
          }
          d={
            // The 36 px cell with D's end padding. Stacked, the panel sits under the list with its own toggle, so the button goes.
            <div className={cn(BESIDE.hiddenStacked, "ps-1 py-1")}>
              <SelectButton
                icon={SvgPanelRight}
                size="md"
                state={panelOpen ? "selected" : "empty"}
                tooltip={panelLabel}
                aria-label={panelLabel}
                onClick={() => onPanelOpenChange(!panelOpen)}
              />
            </div>
          }
        />
      </Card>
      {failed ? (
        <MessageCard variant="error" title={t("loadError")} />
      ) : (
        <Card border="solid" rounding={4} padding={2}>
          {/* A new window or bar count dims only this card until its response lands; the counts above do not depend on it. */}
          <Section
            alignItems="stretch"
            gap={0}
            height="fit"
            className={cn(stale && "opacity-50")}
          >
            <LineLayout
              variant="stat"
              a={figure(data?.indexing_connectors, t("indexingConnectors"))}
              b={figure(data?.recent_docs_indexed, tStats("recentLabel"))}
              c={null}
              d={
                <ThroughputWindowPicker
                  windows={WINDOWS}
                  value={timeWindow}
                  onChange={changeWindow}
                  selection={range}
                  onClearSelection={() => onRangeChange(null)}
                />
              }
            />
            {/* The frame stays while loading, so the chart's width sets the bar count of the first fetch. */}
            <Section padding={2} alignItems="stretch" height="fit">
              <Section ref={ref} alignItems="stretch" height="fit">
                {data !== undefined && (
                  <ThroughputBars
                    data={data.throughput}
                    range={timeWindow}
                    height={BARS_HEIGHT}
                    selection={range}
                    // The dimmed bars are the old window's, so they pick nothing until the new one lands.
                    onRangeSelect={stale ? undefined : onRangeChange}
                    {...activityLinks}
                  />
                )}
              </Section>
            </Section>
          </Section>
        </Card>
      )}
    </Section>
  );
}
