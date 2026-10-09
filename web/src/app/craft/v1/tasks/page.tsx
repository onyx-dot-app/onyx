"use client";

import { IconLoader } from "@opal/loaders";
import { useCallback, useMemo, useState } from "react";
import useSWR from "swr";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { SettingsLayouts, toast } from "@opal/layouts";
import { Section } from "@/layouts/general-layouts";
import {
  Button,
  Table,
  Text,
  Tooltip,
  type TableColumn,
} from "@opal/components";
import { IllustrationContent } from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";
import { ConfirmationModalLayout } from "@opal/layouts";
import { SvgClock, SvgPlus, SvgRefreshCw, SvgTrash } from "@opal/icons";
import { deleteScheduledTask } from "@/app/craft/v1/tasks/api";
import {
  RunStatusBadge,
  TaskStatusBadge,
} from "@/app/craft/v1/tasks/components/StatusBadge";
import {
  NEW_TASK_PATH,
  TASKS_PAGE_SIZE,
  taskDetailPath,
} from "@/app/craft/v1/tasks/constants";
import type {
  ScheduledTaskListItem,
  ScheduledTaskListResponse,
} from "@/app/craft/v1/tasks/interfaces";
import {
  formatAbsolute,
  formatRelativeShort,
} from "@/app/craft/v1/tasks/utils";
import { humanReadableScheduleFromCron } from "@/app/craft/v1/tasks/schedule";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";
type TasksListTranslate = ReturnType<
  typeof useTranslations<"craft.tasks.listPage">
>;

interface RowActionHandlers {
  busyTaskId: string | null;
  onDelete: (task: ScheduledTaskListItem) => void;
}

function buildColumns(
  handlers: RowActionHandlers,
  t: TasksListTranslate
): TableColumn<ScheduledTaskListItem>[] {
  return [
    {
      kind: "data",
      field: "name",
      title: t("columns.name"),
      weight: 25,
      sortable: false,
      cell: (value) => (
        <Text font="main-ui-body" color="text-05" wordWrap="whitespace-nowrap">
          {value}
        </Text>
      ),
    },
    {
      kind: "data",
      field: "human_readable_schedule",
      title: t("columns.schedule"),
      weight: 22,
      sortable: false,
      cell: (value) => (
        <Text font="main-ui-body" color="text-03" wordWrap="whitespace-nowrap">
          {value}
        </Text>
      ),
    },
    {
      kind: "data",
      field: "status",
      title: t("columns.status"),
      weight: 12,
      sortable: false,
      cell: (status) => <TaskStatusBadge status={status} />,
    },
    {
      kind: "data",
      field: "last_run",
      title: t("columns.lastRun"),
      weight: 18,
      sortable: false,
      cell: (lastRun) => {
        if (!lastRun) {
          return (
            <Text font="main-ui-body" color="text-03">
              —
            </Text>
          );
        }
        return (
          <div className="flex flex-col gap-0.5">
            <RunStatusBadge status={lastRun.status} />
            <Text font="secondary-body" color="text-03">
              {formatRelativeShort(lastRun.started_at)}
            </Text>
          </div>
        );
      },
    },
    {
      kind: "data",
      field: "next_run_at",
      title: t("columns.nextRun"),
      weight: 13,
      sortable: false,
      cell: (nextRunAt) => {
        if (!nextRunAt) {
          return (
            <Text font="main-ui-body" color="text-03">
              —
            </Text>
          );
        }
        return (
          <Tooltip tooltip={formatAbsolute(nextRunAt)} side="top">
            <Text
              font="main-ui-body"
              color="text-03"
              wordWrap="whitespace-nowrap"
            >
              {formatRelativeShort(nextRunAt)}
            </Text>
          </Tooltip>
        );
      },
    },
    {
      kind: "actions",
      showColumnVisibility: false,
      showSorting: false,
      cell: (task) => <TaskRowActions task={task} handlers={handlers} />,
    },
  ];
}

export default function ScheduledTasksListPage() {
  const t = useTranslations("craft.tasks.listPage");
  const router = useRouter();
  const { data, error, isLoading, mutate } = useSWR<ScheduledTaskListResponse>(
    SWR_KEYS.scheduledTasks,
    errorHandlingFetcher,
    { revalidateOnFocus: false }
  );
  const tasks = useMemo<ScheduledTaskListItem[]>(
    () =>
      data?.items.map((task) => ({
        ...task,
        human_readable_schedule: humanReadableScheduleFromCron(
          task.editor_mode,
          task.cron_expression
        ),
      })) ?? [],
    [data?.items]
  );
  const [pendingDelete, setPendingDelete] =
    useState<ScheduledTaskListItem | null>(null);
  const [busyTaskId, setBusyTaskId] = useState<string | null>(null);

  const refresh = useCallback(() => {
    void mutate();
  }, [mutate]);

  const handleDelete = useCallback(async () => {
    if (!pendingDelete) return;
    setBusyTaskId(pendingDelete.id);
    try {
      await deleteScheduledTask(pendingDelete.id);
      toast.success(t("toasts.deleted", { name: pendingDelete.name }));
      setPendingDelete(null);
      refresh();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("toasts.deleteFailed")
      );
    } finally {
      setBusyTaskId(null);
    }
  }, [pendingDelete, refresh, t]);

  const columns = useMemo(
    () =>
      buildColumns(
        {
          busyTaskId,
          onDelete: (task) => setPendingDelete(task),
        },
        t
      ),
    [busyTaskId, t]
  );

  const headerActions = useMemo(
    () => (
      <Button
        key="new"
        variant="default"
        prominence="primary"
        icon={SvgPlus}
        href={NEW_TASK_PATH}
        data-testid="new-task-button"
      >
        {t("newTaskButton")}
      </Button>
    ),
    [t]
  );

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgClock}
        title={t("header.title")}
        description={t("header.description")}
        actions={[headerActions]}
      />
      <SettingsLayouts.Body>
        {isLoading ? (
          <div className="flex justify-center py-12">
            <IconLoader className="h-6 w-6" />
          </div>
        ) : error ? (
          <Section gap={2}>
            <Text font="main-ui-body" color="text-03">
              {t("errors.loadFailed")}
            </Text>
            <Button
              variant="default"
              prominence="secondary"
              icon={SvgRefreshCw}
              onClick={refresh}
            >
              {t("errors.tryAgainButton")}
            </Button>
          </Section>
        ) : (
          <Table
            items={tasks}
            columns={columns}
            getRowId={(row) => row.id}
            pageSize={
              tasks.length > 0 ? Math.min(tasks.length, TASKS_PAGE_SIZE) : 1
            }
            selectionBehavior="single-select"
            onRowClick={(row) => router.push(taskDetailPath(row.id))}
            emptyState={
              <IllustrationContent
                illustration={SvgNoResult}
                title={t("empty.title")}
                description={t("empty.description")}
              />
            }
          />
        )}
      </SettingsLayouts.Body>

      {pendingDelete && (
        <ConfirmationModalLayout
          icon={SvgTrash}
          title={t("confirmDelete.title", { name: pendingDelete.name })}
          description={t("confirmDelete.description")}
          onClose={() => setPendingDelete(null)}
          submit={
            <Button
              variant="danger"
              prominence="primary"
              onClick={() => void handleDelete()}
              disabled={busyTaskId === pendingDelete.id}
              data-testid="confirm-delete-task"
            >
              {busyTaskId === pendingDelete.id
                ? t("confirmDelete.deletingButton")
                : t("confirmDelete.deleteButton")}
            </Button>
          }
        />
      )}
    </SettingsLayouts.Root>
  );
}

// ---------------------------------------------------------------------------
// Row actions
// ---------------------------------------------------------------------------

interface TaskRowActionsProps {
  task: ScheduledTaskListItem;
  handlers: RowActionHandlers;
}

function TaskRowActions({ task, handlers }: TaskRowActionsProps) {
  const t = useTranslations("craft.tasks.listPage");
  const disabled = handlers.busyTaskId === task.id;
  return (
    <div className="flex items-center gap-0.5">
      <Tooltip tooltip={t("rowActions.deleteTooltip")} side="top">
        <Button
          icon={SvgTrash}
          variant="danger"
          prominence="tertiary"
          size="sm"
          onClick={() => handlers.onDelete(task)}
          disabled={disabled}
          data-testid={`row-delete-${task.id}`}
        />
      </Tooltip>
    </div>
  );
}
