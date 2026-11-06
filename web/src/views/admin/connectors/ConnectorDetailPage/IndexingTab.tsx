"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Card, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import type { RichStr } from "@opal/types";
import RunsCard from "@/views/admin/connectors/ConnectorDetailPage/RunsCard";
import { FigureStatBlock } from "@/views/admin/connectors/ConnectorDetailPage/StatusCard";
import {
  useCCPairThroughput,
  useLatestIndexAttempt,
} from "@/lib/connectors/ccPair/hooks";
import {
  PAIR_WINDOWS,
  ThroughputChartView,
  ThroughputWindowPicker,
  isEmptyThroughput,
  type PickedWindow,
  type PickerWindow,
  type SliceRange,
  type ThroughputActivityLinks,
} from "@/views/admin/connectors/ConnectorDetailPage/ThroughputChart";
import { focusDimClass } from "@/views/admin/connectors/ConnectorDetailPage/focusMode";

/** A tab card's heading, 2 px in from the card's edge and 24 px tall, as the design draws it. */
function TabHeading({ children }: { children: string | RichStr }) {
  return (
    <Section
      alignItems="start"
      width="auto"
      height="fit"
      className="mx-0.5 min-h-6"
    >
      <Text font="main-content-emphasis" color="text-04">
        {children}
      </Text>
    </Section>
  );
}

interface DocumentIndexingCardProps {
  ccPairId: number;
  timeWindow: PickedWindow;
  onTimeWindowChange: (window: PickerWindow) => void;
  range: SliceRange | null;
  onRangeChange: (range: SliceRange | null) => void;
  /** While a run line's details are open, the chart steps back. */
  dimmed: boolean;
  activityLinks?: ThroughputActivityLinks;
}

/**
 * The documents processed recently and the chart. Hidden once its window
 * loads with no runs and no documents; up while loading and after a load
 * error, which the chart reports in its place.
 */
function DocumentIndexingCard({
  ccPairId,
  timeWindow,
  onTimeWindowChange,
  range,
  onRangeChange,
  dimmed,
  activityLinks,
}: DocumentIndexingCardProps) {
  const t = useTranslations("admin.connector");
  // The chart's own request: hidden, the card keeps its last bar count and polls on, so data brings it back.
  const throughput = useCCPairThroughput(ccPairId, timeWindow.window);
  const { data: latestIndexAttempts } = useLatestIndexAttempt(ccPairId);
  // keepPreviousData holds the last empty response through a failed poll or a new key's load, so an error or a pending request keeps the card up.
  if (
    throughput.error === undefined &&
    throughput.data !== undefined &&
    !throughput.stale &&
    isEmptyThroughput(throughput.data)
  )
    return null;
  return (
    <Section
      alignItems="stretch"
      gap={3}
      height="fit"
      className={focusDimClass(dimmed)}
    >
      <TabHeading>{t("indexingTab.chartHeading")}</TabHeading>
      <Card
        color="background-tint-01"
        border="solid"
        rounding={4}
        padding={2}
        data-testid="connector-document-indexing"
      >
        <Section alignItems="stretch" gap={1} height="fit">
          <Section
            flexDirection="row"
            alignItems="start"
            justifyContent="start"
            gap={1}
            height="fit"
          >
            {/* The figure gives way to the picker, so the picker keeps the first line and a picked span's longer label never pushes the chart down. */}
            <Section
              flexDirection="row"
              alignItems="start"
              justifyContent="start"
              width="auto"
              height="fit"
              // basis-0 lets the figure give way, since width="auto" adds shrink-0.
              className="min-w-0 grow basis-0"
              wrap
            >
              <FigureStatBlock
                value={latestIndexAttempts?.items[0]?.total_docs_indexed ?? 0}
                label={t("statusCard.documents.recentLabel")}
              />
            </Section>
            <Section
              flexDirection="row"
              justifyContent="end"
              alignItems="center"
              width="fit"
              height="fit"
              className="shrink-0"
            >
              <ThroughputWindowPicker
                windows={PAIR_WINDOWS}
                value={timeWindow.window}
                onChange={onTimeWindowChange}
                selection={range}
                onClearSelection={() => onRangeChange(null)}
              />
            </Section>
          </Section>
          {/* The chart sits 12 px in from the card's sides and from the row above. */}
          <Section
            padding={2}
            alignItems="stretch"
            height="fit"
            className="mx-1"
          >
            <ThroughputChartView
              throughput={throughput}
              range={timeWindow.window}
              selection={range}
              onRangeSelect={onRangeChange}
              {...activityLinks}
            />
          </Section>
        </Section>
      </Card>
    </Section>
  );
}

export interface IndexingTabProps {
  ccPairId: number;
  canOperate: boolean;
  timeWindow: PickedWindow;
  onTimeWindowChange: (window: PickerWindow) => void;
  range: SliceRange | null;
  onRangeChange: (range: SliceRange | null) => void;
  /** Ties the chart to the page's activity panel. */
  activityLinks?: ThroughputActivityLinks;
  /** The index attempt of the activity the panel points at: its run line lifts. */
  liftedAttemptId?: number | null;
}

/** The connector page's Indexing tab: the chart card over the runs card, which share one time window and chart span. */
export default function IndexingTab({
  ccPairId,
  canOperate,
  timeWindow,
  onTimeWindowChange,
  range,
  onRangeChange,
  activityLinks,
  liftedAttemptId = null,
}: IndexingTabProps) {
  const t = useTranslations("admin.connector.indexingTab");
  const [runFocus, setRunFocus] = useState(false);
  return (
    <Section alignItems="stretch" gap={6} height="fit">
      <DocumentIndexingCard
        ccPairId={ccPairId}
        timeWindow={timeWindow}
        onTimeWindowChange={onTimeWindowChange}
        range={range}
        onRangeChange={onRangeChange}
        dimmed={runFocus}
        activityLinks={activityLinks}
      />
      <Section alignItems="stretch" gap={3} height="fit">
        <TabHeading>{t("runsHeading")}</TabHeading>
        <RunsCard
          ccPairId={ccPairId}
          canOperate={canOperate}
          sharedWindow={timeWindow}
          onSharedWindowChange={onTimeWindowChange}
          onFocusChange={setRunFocus}
          range={range}
          onClearRange={() => onRangeChange(null)}
          liftedAttemptId={liftedAttemptId}
        />
      </Section>
    </Section>
  );
}
