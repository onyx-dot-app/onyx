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
import { SvgActivity, SvgFileText } from "@opal/icons";
import {
  ALL_ACTIVITY,
  runKey,
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
  const feed = { enabled: true, pollMs: RUNS_POLL_MS };
  const failures = useActivityItems(
    "fleet",
    "failures",
    false,
    ALL_ACTIVITY,
    feed
  );
  const errors = useActivityItems("fleet", "errors", false, ALL_ACTIVITY, feed);
  const sections = [failures, errors];
  // Each feed is newest first, so one sort interleaves them.
  const items = useMemo(
    () =>
      [
        ...failures.runs.map((item) => ({
          section: "failures" as const,
          item,
        })),
        ...errors.runs.map((item) => ({ section: "errors" as const, item })),
      ].sort((a, b) =>
        b.item.run.time_created.localeCompare(a.item.run.time_created)
      ),
    [failures.runs, errors.runs]
  );
  const loading = sections.some(
    (section) => section.isLoading && !section.loaded
  );
  const failed = sections.some((section) => section.failed);
  const empty = sections.every(
    (section) => section.loaded && section.runs.length === 0
  );

  return (
    // Fills the row beside the overview, so the two cards share one height and the list scrolls inside.
    <Card
      border="solid"
      rounding={4}
      padding={2}
      height="full"
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
            font="main-ui-action"
            icon={SvgActivity}
            title={t("title")}
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
          <ShadowDiv
            variant="mask"
            containerClassName="flex-1"
            // Stacked under the overview the feed keeps a cap. Beside it the card's height is the cap.
            className="max-h-44 @[38.5rem]/overview:max-h-none"
          >
            <Section alignItems="stretch" gap={1} height="fit">
              {items.map(({ section, item }) => (
                <ActivityCard
                  key={runKey(item.run)}
                  ccPairId={item.ccPairId}
                  run={item.run}
                  section={section}
                  closed={false}
                  connector={item.connector}
                  canResolve={item.canResolve}
                  canResolveRuns={item.canResolveRuns}
                  resolving={resolving}
                  onResolve={(errorIds) => void resolve(item, errorIds)}
                  onResolveRun={() => void resolveRun(item)}
                  popoverPlacement="below"
                />
              ))}
            </Section>
          </ShadowDiv>
        )}
        {/* Never unfolds in place: the history opens beside the page instead. */}
        <Divider
          title={t("history")}
          foldable
          chevronPosition="start"
          foldedChevron="down"
          open={false}
          onOpenChange={onOpenHistory}
        />
      </Section>
    </Card>
  );
}
