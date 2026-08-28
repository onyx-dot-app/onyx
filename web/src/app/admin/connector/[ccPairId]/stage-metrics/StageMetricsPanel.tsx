"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { MessageCard, Text } from "@opal/components";
import { Section } from "@/layouts/general-layouts";
import useIndexAttemptStageMetrics from "@/hooks/useIndexAttemptStageMetrics";
import { SortMode } from "./interfaces";
import BatchTotalHeader from "./BatchTotalHeader";
import PerBatchSection from "./PerBatchSection";
import AttemptOverhead from "./AttemptOverhead";

interface StageMetricsPanelProps {
  indexAttemptId: number;
}

export default function StageMetricsPanel({
  indexAttemptId,
}: StageMetricsPanelProps) {
  const t = useTranslations("admin.connector");
  const [sortMode, setSortMode] = useState<SortMode>("pipeline");

  const { data, error, isLoading } =
    useIndexAttemptStageMetrics(indexAttemptId);

  const { batchTotal, perBatchStages, attemptStages } = useMemo(() => {
    const stages = data?.stages ?? [];
    const total = stages.find((s) => s.stage === "BATCH_TOTAL") ?? null;
    const perBatch = stages.filter(
      (s) => s.scope === "BATCH_LEVEL" && s.stage !== "BATCH_TOTAL"
    );
    const attempt = stages.filter((s) => s.scope === "ATTEMPT_LEVEL");
    return {
      batchTotal: total,
      perBatchStages: perBatch,
      attemptStages: attempt,
    };
  }, [data]);

  if (isLoading) {
    return (
      <Text font="secondary-body" color="text-03">
        {t("stageMetrics.loading")}
      </Text>
    );
  }

  if (error) {
    return (
      <MessageCard
        variant="warning"
        title={t("stageMetrics.loadError.title")}
        description={t("stageMetrics.loadError.description")}
      />
    );
  }

  if (!data || data.stages.length === 0) {
    return (
      <Text font="secondary-body" color="text-03">
        {t("stageMetrics.empty.description")}
      </Text>
    );
  }

  return (
    <Section alignItems="start" height="fit" width="full" gap={3}>
      <BatchTotalHeader batchTotal={batchTotal} />
      <PerBatchSection
        perBatchStages={perBatchStages}
        sortMode={sortMode}
        onSortModeChange={setSortMode}
      />
      {attemptStages.length > 0 && (
        <AttemptOverhead attemptStages={attemptStages} />
      )}
    </Section>
  );
}
