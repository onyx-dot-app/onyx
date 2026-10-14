"use client";

import { useMemo, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { mutate } from "swr";
import { Card, MessageCard, ShadowDiv, Tag, Text } from "@opal/components";
import { Content, Section, toast } from "@opal/layouts";
import { CardLoader } from "@opal/loaders";
import { SvgActivity, SvgAlertTriangle, SvgXCircle } from "@opal/icons";
import { useFleetActivityGroup } from "@/lib/connectors/ccPair/hooks";
import type { IndexingRun } from "@/lib/connectors/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  resolveAllErrorsForCCPair,
  resolveErrors,
} from "@/lib/targeted_reindex";
import ActivityCard from "@/views/admin/connectors/ConnectorDetailPage/ActivityCard";
import { RUNS_POLL_MS } from "@/views/admin/connectors/ConnectorDetailPage/RunsCard";

const LOADER_ROWS = 2;

/** Clears every feed the resolved documents can appear in. */
export async function refreshFleetActivity(ccPairId: number): Promise<void> {
  await mutate(
    (key) =>
      typeof key === "string" &&
      (key.startsWith(SWR_KEYS.ccPairIndexingErrors(ccPairId)) ||
        key.startsWith(SWR_KEYS.ccPairRunsPrefix(ccPairId)) ||
        key.startsWith(SWR_KEYS.indexMonitoringRunsPrefix))
  );
}

/** Resolves a run's document errors across the fleet feeds. Returns whether the submit landed. */
export function useResolveFleetErrors() {
  const tToasts = useTranslations("admin.connector.toasts");
  const [resolving, setResolving] = useState(false);

  // Awaits only the submit. The feeds poll, so rows clear as documents land.
  async function resolve(
    ccPairId: number,
    indexAttemptId: number,
    errorIds: number[] | null
  ) {
    if (resolving) return;
    setResolving(true);
    try {
      const result =
        errorIds === null
          ? await resolveAllErrorsForCCPair(ccPairId, indexAttemptId)
          : await resolveErrors(errorIds);
      if (result.total_error_ids === 0) {
        toast.success(tToasts("noUnresolvedErrors"));
      } else {
        toast.success(
          tToasts("targetedReindexSubmitted", { count: result.total_error_ids })
        );
      }
      await refreshFleetActivity(ccPairId);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      toast.error(tToasts("targetedReindexFailed", { message }));
    } finally {
      setResolving(false);
    }
  }

  return { resolving, resolve };
}

/** The newest failed runs and runs with document errors across every readable connector. */
export default function ActivitiesCard() {
  const t = useTranslations("admin.indexing.activities");
  const tActivity = useTranslations("admin.connector.activity");
  const format = useFormatter();
  const { resolving, resolve } = useResolveFleetErrors();
  const failures = useFleetActivityGroup("failures", "", true, RUNS_POLL_MS);
  const errors = useFleetActivityGroup("errors", "", true, RUNS_POLL_MS);
  const groups = [failures, errors];
  // Both feeds are newest first, so the merge is too.
  const items = useMemo(
    () =>
      [
        ...failures.runs.map((item) => ({ group: "failures" as const, item })),
        ...errors.runs.map((item) => ({ group: "errors" as const, item })),
      ].sort((a, b) =>
        b.item.run.time_created.localeCompare(a.item.run.time_created)
      ),
    [failures.runs, errors.runs]
  );
  const loading = groups.some((group) => group.isLoading && !group.loaded);
  const failed = groups.some((group) => group.failed);
  const empty = groups.every(
    (group) => group.loaded && group.runs.length === 0
  );

  return (
    <Card
      border="solid"
      rounding={4}
      padding={2}
      data-testid="indexing-activities"
    >
      <Section alignItems="stretch" gap={1} height="full">
        <Section
          flexDirection="row"
          justifyContent="between"
          alignItems="center"
          gap={1}
          height="fit"
          className="shrink-0"
        >
          <Content
            icon={SvgActivity}
            title={t("title")}
            sizePreset="main-ui"
            variant="section"
          />
          <Section
            flexDirection="row"
            justifyContent="end"
            gap={1}
            padding={1}
            width="fit"
            height="fit"
          >
            <Tag
              icon={SvgXCircle}
              title={format.number(failures.total)}
              tooltip={tActivity("counts.failures", { count: failures.total })}
              color="red"
            />
            <Tag
              icon={SvgAlertTriangle}
              title={format.number(errors.total)}
              tooltip={tActivity("counts.errors", { count: errors.total })}
              color="amber"
            />
          </Section>
        </Section>
        {failed ? (
          <MessageCard variant="error" title={tActivity("loadError.title")} />
        ) : loading ? (
          <Section alignItems="stretch" gap={1} height="fit">
            {Array.from({ length: LOADER_ROWS }, (_, index) => (
              <CardLoader
                key={index}
                color="background-tint-00"
                border="none"
                rounding={2}
                padding={2}
              />
            ))}
          </Section>
        ) : empty ? (
          <Section
            alignItems="center"
            justifyContent="center"
            padding={2}
            height="fit"
          >
            <Text font="secondary-body" color="text-03">
              {tActivity("empty.title")}
            </Text>
          </Section>
        ) : (
          <ShadowDiv variant="mask" className="max-h-44 min-h-0">
            <Section alignItems="stretch" gap={1} height="fit">
              {items.map(({ group, item }) => (
                <ActivityCard
                  key={`${item.run.kind}-${item.run.attempt.id}`}
                  ccPairId={item.cc_pair.id}
                  run={item.run}
                  group={group}
                  connector={item.cc_pair}
                  canResolve={item.cc_pair.can_resolve}
                  resolving={resolving}
                  onResolve={(errorIds) =>
                    void resolve(item.cc_pair.id, item.run.attempt.id, errorIds)
                  }
                />
              ))}
            </Section>
          </ShadowDiv>
        )}
      </Section>
    </Card>
  );
}
