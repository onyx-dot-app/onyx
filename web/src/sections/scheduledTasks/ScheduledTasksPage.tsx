"use client";

import { useState } from "react";
import useSWR from "swr";
import { useLocale, useTranslations } from "next-intl";
import {
  Button,
  Dropdown,
  InputTypeIn,
  Table,
  Text,
  Tooltip,
  type TableColumn,
} from "@opal/components";
import { IllustrationContent, Section, SettingsLayouts } from "@opal/layouts";
import { SvgFilter, SvgPlus } from "@opal/icons";
import { SvgLongWait, SvgNoResult } from "@opal/illustrations";
import { useScreenSize } from "@opal/hooks";
import { useNavigation } from "@opal/navigation";
import UnseenMarker from "@/app/craft/components/UnseenMarker";
import { errorHandlingFetcher } from "@/lib/fetcher";
import {
  TASK_REFRESH_INTERVAL_MS,
  useScheduledTaskFormat,
} from "@/lib/scheduledTasks/hooks";
import {
  NEW_SCHEDULED_TASK_PATH,
  scheduledTaskHref,
} from "@/lib/scheduledTasks/paths";
import type {
  ScheduledTaskListItem,
  ScheduledTaskListResponse,
} from "@/lib/scheduledTasks/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import { CustomizeEmpty } from "@/sections/customize/CustomizeList";
import ScheduledTaskMenu from "@/sections/scheduledTasks/ScheduledTaskMenu";
import {
  RunStatusBadge,
  TaskStatusBadge,
} from "@/sections/scheduledTasks/StatusBadges";

type TaskFilter = "all" | "ACTIVE" | "PAUSED" | "unviewed";

function isTaskFilter(value: string): value is TaskFilter {
  return (
    value === "all" ||
    value === "ACTIVE" ||
    value === "PAUSED" ||
    value === "unviewed"
  );
}

function matchesFilter(task: ScheduledTaskListItem, filter: TaskFilter) {
  if (filter === "all") return true;
  if (filter === "unviewed") return task.unviewed_run_count > 0;
  return task.status === filter;
}

export default function ScheduledTasksPage() {
  const t = useTranslations("scheduledTasks.list");
  const tTasks = useTranslations("scheduledTasks");
  const locale = useLocale();
  const navigation = useNavigation();
  const { isMobile } = useScreenSize();
  const timeFormat = useScheduledTaskFormat();
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<TaskFilter>("all");
  const { data, error, isLoading } = useSWR<ScheduledTaskListResponse>(
    SWR_KEYS.chatScheduledTasks,
    errorHandlingFetcher,
    // Runs end and next runs move in the background.
    { refreshInterval: TASK_REFRESH_INTERVAL_MS }
  );
  const tasks = data?.items ?? [];
  const search = query.trim().toLocaleLowerCase(locale);
  const shown = tasks.filter(
    (task) =>
      matchesFilter(task, filter) &&
      task.name.toLocaleLowerCase(locale).includes(search)
  );

  const detailColumns: TableColumn<ScheduledTaskListItem>[] = [
    {
      kind: "display",
      id: "schedule",
      title: t("columns.schedule"),
      width: { weight: 22 },
      cell: (row) => (
        <Text as="p" font="main-ui-body" color="text-03" maxLines={1}>
          {timeFormat.schedule(
            row.editor_mode,
            row.cron_expression,
            row.next_run_at
          )}
        </Text>
      ),
    },
    {
      kind: "display",
      id: "lastRun",
      title: t("columns.lastRun"),
      width: { weight: 18 },
      cell: (row) =>
        row.last_run ? (
          <Section
            flexDirection="row"
            justifyContent="start"
            height="auto"
            gap={1}
          >
            <RunStatusBadge status={row.last_run.status} />
            <Text as="p" font="secondary-body" color="text-03" maxLines={1}>
              {timeFormat.relative(row.last_run.started_at)}
            </Text>
          </Section>
        ) : (
          <Text as="p" font="main-ui-body" color="text-03">
            {t("never")}
          </Text>
        ),
    },
    {
      kind: "display",
      id: "nextRun",
      title: t("columns.nextRun"),
      width: { weight: 14 },
      cell: (row) =>
        row.next_run_at && row.status === "ACTIVE" ? (
          <Tooltip tooltip={timeFormat.absolute(row.next_run_at)} side="top">
            <Text as="p" font="main-ui-body" color="text-03" maxLines={1}>
              {timeFormat.relative(row.next_run_at)}
            </Text>
          </Tooltip>
        ) : (
          <Text as="p" font="main-ui-body" color="text-03">
            {t("notScheduled")}
          </Text>
        ),
    },
  ];
  const columns: TableColumn<ScheduledTaskListItem>[] = [
    {
      kind: "data",
      field: "name",
      title: t("columns.name"),
      weight: 30,
      truncate: true,
      cell: (name, row) => (
        <Section
          flexDirection="row"
          justifyContent="start"
          height="auto"
          gap={1.5}
        >
          {row.unviewed_run_count > 0 && (
            <UnseenMarker
              label={tTasks("unviewedResults")}
              className="shrink-0"
            />
          )}
          <Text as="p" font="main-ui-action" color="text-04" maxLines={1}>
            {name}
          </Text>
        </Section>
      ),
    },
    ...(isMobile ? [] : detailColumns),
    {
      kind: "display",
      id: "status",
      title: t("columns.status"),
      width: { weight: 16 },
      cell: (row) => (
        <Section
          flexDirection="row"
          justifyContent="end"
          alignItems="center"
          height="auto"
          gap={1}
        >
          <TaskStatusBadge status={row.status} />
          <ScheduledTaskMenu task={row} />
        </Section>
      ),
    },
  ];

  return (
    <SettingsLayouts.Root
      width="lg"
      loading={isLoading}
      error={error ? t("loadFailed") : false}
    >
      <SettingsLayouts.Header title={t("title")} description={t("description")}>
        <Section
          flexDirection="row"
          justifyContent="between"
          alignItems="center"
          height="auto"
          gap={0.5}
        >
          <Section
            flexDirection="row"
            justifyContent="start"
            alignItems="center"
            width="auto"
            height="auto"
            gap={0.5}
          >
            <Section height="auto" basis={16}>
              <InputTypeIn
                icon="search"
                value={query}
                placeholder={t("search")}
                aria-label={t("search")}
                onChange={(event) => setQuery(event.target.value)}
              />
            </Section>
            <Dropdown align="end" width={60}>
              <Dropdown.Trigger asChild>
                <Button
                  prominence="tertiary"
                  icon={SvgFilter}
                  interaction={filter === "all" ? "rest" : "hover"}
                  aria-label={t("filter.label")}
                  tooltip={t("filter.label")}
                />
              </Dropdown.Trigger>
              <Dropdown.Data
                label={t("filter.label")}
                items={[
                  { kind: "option", value: "all", title: t("filter.all") },
                  {
                    kind: "option",
                    value: "ACTIVE",
                    title: tTasks("taskStatus", { status: "ACTIVE" }),
                  },
                  {
                    kind: "option",
                    value: "PAUSED",
                    title: tTasks("taskStatus", { status: "PAUSED" }),
                  },
                  {
                    kind: "option",
                    value: "unviewed",
                    title: t("filter.unviewed"),
                  },
                ]}
                value={filter}
                onSelect={(option) => {
                  if (isTaskFilter(option.value)) setFilter(option.value);
                }}
              />
            </Dropdown>
          </Section>
          <Button
            icon={SvgPlus}
            {...navigation.linkTo(NEW_SCHEDULED_TASK_PATH)}
            data-testid="new-scheduled-task"
          >
            {t("new")}
          </Button>
        </Section>
      </SettingsLayouts.Header>
      <SettingsLayouts.Body>
        {tasks.length === 0 ? (
          <CustomizeEmpty
            illustration={SvgLongWait}
            title={t("empty.title")}
            description={t("empty.description")}
          />
        ) : (
          <Table
            label={t("title")}
            items={shown}
            columns={columns}
            getRowId={(row) => row.id}
            pageSize={false}
            onRowClick={(row) => navigation.go(scheduledTaskHref(row.id))}
            getRowLabel={(row) => t("open", { name: row.name })}
            emptyState={
              <IllustrationContent
                illustration={SvgNoResult}
                title={t("noMatches.title")}
                description={t("noMatches.description")}
              />
            }
          />
        )}
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
