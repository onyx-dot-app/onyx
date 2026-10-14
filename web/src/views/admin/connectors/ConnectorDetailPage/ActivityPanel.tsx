"use client";

import { useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import {
  Button,
  Card,
  Divider,
  Dropdown,
  FilterButton,
  InputTypeIn,
  MessageCard,
  SelectButton,
  Tag,
} from "@opal/components";
import { useDebouncedValue } from "@opal/hooks";
import { IllustrationContent, Section } from "@opal/layouts";
import { CardLoader } from "@opal/loaders";
import { SvgActivity, SvgAlertTriangle, SvgEye, SvgXCircle } from "@opal/icons";
import type { CCPairRun } from "@/lib/connectors/types";
import {
  useActivityGroup,
  type ActivityGroupState,
} from "@/lib/connectors/ccPair/hooks";
import ExceptionTraceModal from "@/sections/modals/PreviewModal/ExceptionTraceModal";
import ActivityCard from "@/views/admin/connectors/ConnectorDetailPage/ActivityCard";
import { runErrorText } from "@/views/admin/connectors/ConnectorDetailPage/RunRow";
import {
  RUNS_POLL_MS,
  SEARCH_DELAY_MS,
} from "@/views/admin/connectors/ConnectorDetailPage/RunsCard";

const LOADER_ROWS = 2;

/** Which groups the filter shows. Resolved runs replace both when toggled on. */
type Shown = "all" | "failures" | "errors";
const SHOWN: Shown[] = ["all", "failures", "errors"];

interface GroupListProps {
  state: ActivityGroupState;
  onViewTrace: (run: CCPairRun) => void;
}
function GroupList({ state, onViewTrace }: GroupListProps) {
  const t = useTranslations("admin.connector.activity");
  if (state.runs.length === 0) return null;
  return (
    <Section alignItems="stretch" gap={1} height="fit">
      <Divider title={t(`groups.${state.group}`, { count: state.total })} />
      {state.runs.map((run) => (
        <ActivityCard
          key={`${run.kind}-${run.attempt.id}`}
          run={run}
          group={state.group}
          onViewTrace={() => onViewTrace(run)}
        />
      ))}
      {state.hasMore && (
        <Section alignItems="center" height="fit">
          <Button prominence="tertiary" size="xs" onClick={state.more}>
            {t("more")}
          </Button>
        </Section>
      )}
    </Section>
  );
}

export interface ActivityPanelProps {
  ccPairId: number;
}

/** The pair's failed runs and runs with document errors, newest first, with the resolved ones a toggle away. */
export default function ActivityPanel({ ccPairId }: ActivityPanelProps) {
  const t = useTranslations("admin.connector.activity");
  const tRuns = useTranslations("admin.connector.runs");
  const format = useFormatter();
  const [searchInput, setSearchInput] = useState("");
  const search = useDebouncedValue(searchInput.trim(), SEARCH_DELAY_MS);
  const [shown, setShown] = useState<Shown>("all");
  const [resolved, setResolved] = useState(false);
  const [traceRun, setTraceRun] = useState<CCPairRun | null>(null);

  // The failures and errors totals head the panel, so both always poll.
  const failures = useActivityGroup(
    ccPairId,
    "failures",
    search,
    true,
    RUNS_POLL_MS
  );
  const errors = useActivityGroup(
    ccPairId,
    "errors",
    search,
    true,
    RUNS_POLL_MS
  );
  const resolvedRuns = useActivityGroup(
    ccPairId,
    "resolved",
    search,
    resolved,
    RUNS_POLL_MS
  );
  const groups = resolved
    ? [resolvedRuns]
    : [
        ...(shown !== "errors" ? [failures] : []),
        ...(shown !== "failures" ? [errors] : []),
      ];
  const loading = groups.some((group) => group.isLoading && !group.loaded);
  const failed = groups.some((group) => group.failed);
  const empty = groups.every(
    (group) => group.loaded && group.runs.length === 0
  );
  const emptyTitle =
    search !== ""
      ? t("empty.filtered")
      : resolved
        ? t("empty.resolved")
        : shown === "all"
          ? t("empty.title")
          : t(`empty.${shown}`);

  // Full width once the page stacks its columns, the panel's own width beside them.
  return (
    <Section
      alignItems="stretch"
      width="full"
      height="fit"
      className="lg:max-w-104 lg:shrink-0"
      data-testid="connector-activity"
    >
      {traceRun !== null && (
        <ExceptionTraceModal
          onOutsideClick={() => setTraceRun(null)}
          exceptionTrace={runErrorText(traceRun) ?? ""}
          title={tRuns(`errorModal.${traceRun.kind}`)}
        />
      )}
      <Card border="solid" rounding={4} padding={2}>
        <Section alignItems="stretch" gap={3} height="fit">
          <Section alignItems="stretch" gap={1} height="fit">
            <Section
              flexDirection="row"
              justifyContent="between"
              alignItems="center"
              gap={1}
              height="fit"
            >
              <Section height="fit" className="min-w-0 flex-1">
                <InputTypeIn
                  searchIcon
                  variant="internal"
                  placeholder={t("search.placeholder")}
                  value={searchInput}
                  onChange={(event) => setSearchInput(event.target.value)}
                />
              </Section>
              <Section
                flexDirection="row"
                justifyContent="end"
                gap={2}
                padding={1.5}
                width="fit"
                height="fit"
              >
                <Tag
                  icon={SvgXCircle}
                  title={format.number(failures.total)}
                  tooltip={t("counts.failures", { count: failures.total })}
                  color="red"
                />
                <Tag
                  icon={SvgAlertTriangle}
                  title={format.number(errors.total)}
                  tooltip={t("counts.errors", { count: errors.total })}
                  color="amber"
                />
              </Section>
            </Section>
            <Section
              flexDirection="row"
              justifyContent="start"
              gap={1}
              height="fit"
              wrap
            >
              <Dropdown>
                <Dropdown.Trigger asChild>
                  <FilterButton
                    icon={SvgActivity}
                    active={shown !== "all"}
                    onClear={() => setShown("all")}
                  >
                    {t(`filter.${shown}`)}
                  </FilterButton>
                </Dropdown.Trigger>
                <Dropdown.Data
                  label={t("filter.label")}
                  value={shown}
                  onSelect={(option) =>
                    setShown(
                      SHOWN.find((candidate) => candidate === option.value) ??
                        "all"
                    )
                  }
                  items={SHOWN.map((candidate) => ({
                    kind: "option" as const,
                    value: candidate,
                    title: t(`filter.${candidate}`),
                  }))}
                />
              </Dropdown>
              <SelectButton
                icon={SvgEye}
                state={resolved ? "selected" : "empty"}
                aria-pressed={resolved}
                onClick={() => setResolved((current) => !current)}
              >
                {t("resolved.label")}
              </SelectButton>
            </Section>
          </Section>

          {failed ? (
            <MessageCard variant="error" title={t("loadError.title")} />
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
            <IllustrationContent title={emptyTitle} />
          ) : (
            groups.map((group) => (
              <GroupList
                key={group.group}
                state={group}
                onViewTrace={setTraceRun}
              />
            ))
          )}
        </Section>
      </Card>
    </Section>
  );
}
