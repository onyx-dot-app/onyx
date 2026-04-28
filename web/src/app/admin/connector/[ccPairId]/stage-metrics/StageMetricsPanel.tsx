"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";
import { MessageCard, Text } from "@opal/components";
import * as GeneralLayouts from "@/layouts/general-layouts";
import { errorHandlingFetcher, skipRetryOnAuthError } from "@/lib/fetcher";
import { IndexAttemptStageMetricsResponse } from "@/lib/types";
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
  const [sortMode, setSortMode] = useState<SortMode>("pipeline");

  const { data, error, isLoading } = useSWR<IndexAttemptStageMetricsResponse>(
    `/api/manage/admin/index-attempt/${indexAttemptId}/stage-metrics`,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      onErrorRetry: skipRetryOnAuthError,
    }
  );

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
        Loading stage metrics…
      </Text>
    );
  }

  if (error) {
    return (
      <MessageCard
        variant="warning"
        title="Failed to load stage metrics"
        description="Stage timing data could not be loaded for this attempt. The pipeline runs even when metric recording is unavailable, so this does not indicate a problem with the indexing run itself."
      />
    );
  }

  if (!data || data.stages.length === 0) {
    return (
      <Text font="secondary-body" color="text-03">
        No stage timing data has been recorded for this attempt yet. Older
        attempts that ran before stage instrumentation was deployed will not
        have metrics.
      </Text>
    );
  }

  return (
    <GeneralLayouts.Section
      alignItems="start"
      height="fit"
      width="full"
      gap={0.75}
    >
      <BatchTotalHeader batchTotal={batchTotal} />
      <PerBatchSection
        perBatchStages={perBatchStages}
        sortMode={sortMode}
        onSortModeChange={setSortMode}
      />
      {attemptStages.length > 0 && (
        <AttemptOverhead attemptStages={attemptStages} />
      )}
    </GeneralLayouts.Section>
  );
}
