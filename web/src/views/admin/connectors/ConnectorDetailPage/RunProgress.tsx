"use client";

import { useFormatter, useTranslations } from "next-intl";
import { ProgressBar, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import type { IndexAttemptProgress } from "@/lib/types";
import { formatRunLength } from "@/views/admin/connectors/ConnectorDetailPage/runLength";

interface StageBarProps {
  label: string;
  value: number;
  max: number;
}
/** One stage of the run: its name, its bar and its share of the total. */
function StageBar({ label, value, max }: StageBarProps) {
  const format = useFormatter();
  const share = max > 0 ? Math.min(1, value / max) : 0;
  return (
    <Section gap={0.25} height="fit" alignItems="stretch">
      <Section
        flexDirection="row"
        justifyContent="between"
        gap={0.5}
        height="fit"
      >
        <Text font="secondary-body" color="text-03">
          {label}
        </Text>
        <Text font="secondary-action" color="text-04">
          {format.number(share, { style: "percent", maximumFractionDigits: 0 })}
        </Text>
      </Section>
      <ProgressBar value={value} max={max} aria-label={label} />
    </Section>
  );
}

export interface RunProgressProps {
  progress: IndexAttemptProgress;
}

/**
 * Progress of a running index attempt that lists, converts and indexes in
 * separate stages. While the listing runs the total is not known, so it shows
 * the count so far. After that it shows one bar for each stage. It sits in the
 * run's card, padded as the line's parts are, so the bars line up with them.
 */
export default function RunProgress({ progress }: RunProgressProps) {
  const t = useTranslations("admin.connector.runs.progress");
  const format = useFormatter();
  const total = progress.batches_total;

  return (
    <Section
      gap={0.5}
      padding={2}
      height="fit"
      alignItems="stretch"
      data-testid="run-progress"
    >
      {!progress.listing_done || total === null ? (
        <Text font="secondary-body" color="text-03">
          {t("listedSoFar", { count: progress.docs_listed })}
        </Text>
      ) : (
        <Section
          flexDirection="row"
          gap={1}
          height="fit"
          alignItems="start"
          className="@max-[38.75rem]:flex-col"
        >
          <StageBar label={t("listed")} value={total} max={total} />
          <StageBar
            label={t("converted")}
            value={progress.batches_converted}
            max={total}
          />
          <StageBar
            label={t("indexed")}
            value={progress.batches_indexed}
            max={total}
          />
        </Section>
      )}
      <Section
        flexDirection="row"
        justifyContent="between"
        gap={1}
        height="fit"
      >
        <Text font="secondary-body" color="text-03">
          {progress.docs_skipped > 0
            ? t("skipped", { count: progress.docs_skipped })
            : ""}
        </Text>
        {progress.eta_seconds !== null && (
          <Text font="secondary-body" color="text-03">
            {t("eta", {
              duration: formatRunLength(format, progress.eta_seconds * 1000),
            })}
          </Text>
        )}
      </Section>
    </Section>
  );
}
