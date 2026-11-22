"use client";

import type { RichStr } from "@opal/types";
import { useFormatter, useTranslations } from "next-intl";
import { Card, MessageCard, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { PageLoader } from "@opal/loaders";
import { useSearchActivity } from "@/lib/service-status/hooks";
import SearchLatencyChart from "@/views/admin/ServiceStatusPage/SearchLatencyChart";
import SearchLoadChart from "@/views/admin/ServiceStatusPage/SearchLoadChart";
import ValueWithUnit from "@/views/admin/ServiceStatusPage/ValueWithUnit";

const MINUTE_MS = 60_000;

interface HeadlineProps {
  title: string | RichStr;
  value: string;
  unit?: string | RichStr;
  // What the value is, on the right of the value line.
  note?: string | RichStr;
}

function Headline({ title, value, unit, note }: HeadlineProps) {
  return (
    <Section gap={0.25} alignItems="start" width="full">
      <Text as="p" font="secondary-body" color="text-03">
        {title}
      </Text>
      <Section
        flexDirection="row"
        justifyContent="between"
        alignItems="end"
        width="full"
      >
        <ValueWithUnit value={value} unit={unit} size="headline" />
        {note && (
          <Text as="p" font="secondary-body" color="text-03">
            {note}
          </Text>
        )}
      </Section>
    </Section>
  );
}

export default function SearchActivityCard() {
  const t = useTranslations("admin.serviceStatus.searches");
  const format = useFormatter();
  const { data, error } = useSearchActivity();

  if (error) {
    return <MessageCard variant="error" title={t("loadFailed")} />;
  }
  if (!data) {
    return (
      <Card border="solid" rounding={4} padding={4}>
        <PageLoader />
      </Card>
    );
  }

  const endMs = (data.rate.at(-1)?.minute_ms ?? Date.now()) + MINUTE_MS;
  const startMs = endMs - data.window_minutes * MINUTE_MS;
  const windowSeconds = data.rate.reduce(
    (sum, point) => sum + point.seconds,
    0
  );
  const callsPerSecond =
    windowSeconds > 0 ? data.total_count / windowSeconds : 0;
  const formatTime = (ms: number) =>
    format.dateTime(new Date(ms), {
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    });
  // The headline shows the number in bold and its unit with the muted text.
  const p90Parts =
    data.p90_ms === null
      ? null
      : data.p90_ms >= 1000
        ? {
            value: format.number(data.p90_ms / 1000, {
              maximumFractionDigits: 1,
            }),
            unit: t("secondsUnit"),
          }
        : {
            value: format.number(data.p90_ms, { maximumFractionDigits: 1 }),
            unit: t("millisecondsUnit"),
          };
  const formatDuration = (ms: number) =>
    ms >= 1000
      ? t("seconds", {
          value: format.number(ms / 1000, { maximumFractionDigits: 1 }),
        })
      : t("milliseconds", {
          value: format.number(ms, { maximumFractionDigits: 0 }),
        });
  // A quiet window still shows its rate: 2 searches in 30 minutes is 0.001/s.
  const formatRate = (perSecond: number) =>
    perSecond === 0 || perSecond >= 1
      ? format.number(perSecond, { maximumFractionDigits: 1 })
      : format.number(perSecond, { maximumSignificantDigits: 2 });

  const renderLoadTooltip = (
    atMs: number,
    perSecond: number,
    failed: number
  ) => (
    <Card border="solid" rounding={2} padding={2}>
      <Section gap={0.25} alignItems="start" width="fit">
        <Text as="p" font="secondary-body" color="text-05">
          {t("rateTooltip", { rate: formatRate(perSecond) })}
        </Text>
        {failed > 0 && (
          <Text as="p" font="secondary-body" color="status-error-05">
            {t("failedInMinute", { count: failed })}
          </Text>
        )}
        <Text as="p" font="secondary-body" color="text-03">
          {formatTime(atMs)}
        </Text>
      </Section>
    </Card>
  );

  const describeMinute = (minuteMs: number) => {
    const point = data.rate.find((minute) => minute.minute_ms === minuteMs);
    return t("minuteLabel", {
      time: formatTime(minuteMs),
      p90: point?.p90_ms != null ? formatDuration(point.p90_ms) : "—",
      p10: point?.p10_ms != null ? formatDuration(point.p10_ms) : "—",
    });
  };

  const renderMinute = (minuteMs: number) => {
    const point = data.rate.find((minute) => minute.minute_ms === minuteMs);
    if (!point || point.p10_ms === null || point.p90_ms === null) return null;
    return (
      <Card border="solid" rounding={2} padding={2}>
        <Section gap={0.25} alignItems="start" width="fit">
          <Text as="p" font="secondary-body" color="text-05">
            {t("p90Row", { value: formatDuration(point.p90_ms) })}
          </Text>
          <Text as="p" font="secondary-body" color="text-05">
            {t("p10Row", { value: formatDuration(point.p10_ms) })}
          </Text>
          <Text as="p" font="secondary-body" color="text-03">
            {formatTime(point.minute_ms)}
          </Text>
        </Section>
      </Card>
    );
  };

  return (
    <Card border="solid" rounding={4} padding={4}>
      <Section flexDirection="row" gap={2} alignItems="start" width="full">
        <Section gap={1} alignItems="stretch" width="full">
          <Headline
            title={t("loadTitle")}
            value={formatRate(callsPerSecond)}
            unit={t("loadUnit")}
          />
          <SearchLoadChart
            rate={data.rate}
            startMs={startMs}
            endMs={endMs}
            formatTime={formatTime}
            renderTooltip={renderLoadTooltip}
          />
        </Section>
        <Section gap={1} alignItems="stretch" width="full">
          <Headline
            title={t("timeTitle")}
            value={p90Parts === null ? "—" : p90Parts.value}
            unit={p90Parts?.unit}
            note={t("p90Note")}
          />
          {/* Drawn even when empty, so both charts keep the same time axis. */}
          <SearchLatencyChart
            rate={data.rate}
            slowP90Ms={data.slow_p90_ms}
            samples={data.samples}
            startMs={startMs}
            endMs={endMs}
            formatTime={formatTime}
            renderMinute={renderMinute}
            describeMinute={describeMinute}
          />
        </Section>
      </Section>
    </Card>
  );
}
