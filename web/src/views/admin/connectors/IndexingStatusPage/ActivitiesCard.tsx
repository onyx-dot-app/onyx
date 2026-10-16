"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  Card,
  Divider,
  MessageCard,
  ShadowDiv,
  Text,
} from "@opal/components";
import { Content, Section } from "@opal/layouts";
import { CardLoader } from "@opal/loaders";
import { SvgActivity, SvgChevronDown, SvgFileText } from "@opal/icons";
import {
  useActivityItems,
  useResolveRunErrors,
} from "@/lib/connectors/ccPair/hooks";
import ActivityCard from "@/views/admin/connectors/ConnectorDetailPage/ActivityCard";
import { ActivityCountTags } from "@/views/admin/connectors/ConnectorDetailPage/ActivityPanel";
import { RUNS_POLL_MS } from "@/views/admin/connectors/ConnectorDetailPage/RunsCard";

const LOADER_ROWS = 2;

export interface ActivitiesCardProps {
  /** Opens the full activity history beside the page. */
  onOpenHistory: () => void;
}

/** The newest failed runs and runs with document errors across every readable connector. */
export default function ActivitiesCard({ onOpenHistory }: ActivitiesCardProps) {
  const t = useTranslations("admin.indexing.activities");
  const tActivity = useTranslations("admin.connector.activity");
  const { resolving, resolve, resolveRun } = useResolveRunErrors();
  const failures = useActivityItems(
    "fleet",
    "failures",
    false,
    "",
    true,
    RUNS_POLL_MS
  );
  const errors = useActivityItems(
    "fleet",
    "errors",
    false,
    "",
    true,
    RUNS_POLL_MS
  );
  const groups = [failures, errors];
  // Each feed is newest first, so one sort interleaves them.
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
            alignItems="center"
            gap={1}
            width="fit"
            height="fit"
          >
            <ActivityCountTags
              failures={failures.total}
              errors={errors.total}
            />
            <Button
              icon={SvgFileText}
              prominence="tertiary"
              tooltip={t("viewLogs")}
              aria-label={t("viewLogs")}
              onClick={onOpenHistory}
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
                  ccPairId={item.ccPairId}
                  run={item.run}
                  group={group}
                  closed={false}
                  connector={item.connector}
                  canResolve={item.canResolve}
                  canResolveRuns={item.canResolveRuns}
                  resolving={resolving}
                  onResolve={(errorIds) => void resolve(item, errorIds)}
                  onResolveRun={() => void resolveRun(item)}
                />
              ))}
            </Section>
          </ShadowDiv>
        )}
        {/* The toggle sits inside the divider as its label. */}
        <Section
          flexDirection="row"
          alignItems="center"
          gap={0}
          height="fit"
          className="shrink-0"
        >
          <Divider paddingParallel={0} paddingPerpendicular={0} />
          <Button
            icon={SvgChevronDown}
            prominence="tertiary"
            size="xs"
            onClick={onOpenHistory}
          >
            {t("history")}
          </Button>
          <Section height="fit" className="min-w-0 flex-1">
            <Divider paddingParallel={0} paddingPerpendicular={0} />
          </Section>
        </Section>
      </Section>
    </Card>
  );
}
