"use client";

import { useCallback, useMemo, useState } from "react";
import useSWR from "swr";
import { useRouter } from "next/navigation";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { Section } from "@/layouts/general-layouts";
import Card from "@/refresh-components/cards/Card";
import Text from "@/refresh-components/texts/Text";
import { Button, Table, Tooltip, createTableColumns } from "@opal/components";
import { toast } from "@/hooks/useToast";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import { SvgClock, SvgPlus, SvgRefreshCw, SvgTrash } from "@opal/icons";
import { deleteScheduledTask } from "@/app/craft/v1/tasks/api";
import {
  RunStatusBadge,
  TaskStatusBadge,
} from "@/app/craft/v1/tasks/components/StatusBadge";
import {
  NEW_TASK_PATH,
  STARTER_PROMPTS,
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
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";

const tc = createTableColumns<ScheduledTaskListItem>();

interface RowActionHandlers {
  busyTaskId: string | null;
  onDelete: (task: ScheduledTaskListItem) => void;
}

function buildColumns(handlers: RowActionHandlers) {
  return [
    tc.column("name", {
      header: "Name",
      weight: 25,
      enableSorting: false,
      cell: (value) => (
        <Text mainUiBody text05 nowrap>
          {value}
        </Text>
      ),
    }),
    tc.column("human_readable_schedule", {
      header: "Schedule",
      weight: 22,
      enableSorting: false,
      cell: (value) => (
        <Text mainUiBody text03 nowrap>
          {value}
        </Text>
      ),
    }),
    tc.column("status", {
      header: "Status",
      weight: 12,
      enableSorting: false,
      cell: (status) => <TaskStatusBadge status={status} />,
    }),
    tc.column("last_run", {
      header: "Last run",
      weight: 18,
      enableSorting: false,
      cell: (lastRun) => {
        if (!lastRun) {
          return (
            <Text mainUiBody text03>
              —
            </Text>
          );
        }
        return (
          <div className="flex flex-col gap-0.5">
            <RunStatusBadge status={lastRun.status} />
            <Text secondaryBody text03>
              {formatRelativeShort(lastRun.started_at)}
            </Text>
          </div>
        );
      },
    }),
    tc.column("next_run_at", {
      header: "Next run",
      weight: 13,
      enableSorting: false,
      cell: (nextRunAt) => {
        if (!nextRunAt) {
          return (
            <Text mainUiBody text03>
              —
            </Text>
          );
        }
        return (
          <Tooltip tooltip={formatAbsolute(nextRunAt)} side="top">
            <Text mainUiBody text03 nowrap>
              {formatRelativeShort(nextRunAt)}
            </Text>
          </Tooltip>
        );
      },
    }),
    tc.actions({
      showColumnVisibility: false,
      showSorting: false,
      cell: (task) => <TaskRowActions task={task} handlers={handlers} />,
    }),
  ];
}

export default function ScheduledTasksListPage() {
  const router = useRouter();
  const { data, error, isLoading, mutate } = useSWR<ScheduledTaskListResponse>(
    SWR_KEYS.scheduledTasks,
    errorHandlingFetcher,
    { revalidateOnFocus: false }
  );
  const tasks = data?.items;
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
      toast.success(`Deleted "${pendingDelete.name}".`);
      setPendingDelete(null);
      refresh();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete task");
    } finally {
      setBusyTaskId(null);
    }
  }, [pendingDelete, refresh]);

  const columns = useMemo(
    () =>
      buildColumns({
        busyTaskId,
        onDelete: (task) => setPendingDelete(task),
      }),
    [busyTaskId]
  );

  const headerActions = useMemo(
    () => (
      <Button
        variant="default"
        prominence="primary"
        icon={SvgPlus}
        href={NEW_TASK_PATH}
        data-testid="new-task-button"
      >
        New scheduled task
      </Button>
    ),
    []
  );

  return (
    <SettingsLayouts.Root width="lg">
      <SettingsLayouts.Header
        icon={SvgClock}
        title="Scheduled Tasks"
        description="Run Craft prompts on a timer. Each fire creates a fresh session that runs in the background."
        rightChildren={headerActions}
      />
      <SettingsLayouts.Body>
        {isLoading ? (
          <div className="flex justify-center py-12">
            <SimpleLoader className="h-6 w-6" />
          </div>
        ) : error ? (
          <Section gap={0.5}>
            <Text mainUiBody text03>
              Failed to load scheduled tasks.
            </Text>
            <Button
              variant="default"
              prominence="secondary"
              icon={SvgRefreshCw}
              onClick={refresh}
            >
              Try again
            </Button>
          </Section>
        ) : !tasks || tasks.length === 0 ? (
          <EmptyState
            onSelectStarter={(prompt) => {
              const params = new URLSearchParams({
                starter: prompt.title,
                prompt: prompt.prompt,
                mode: prompt.mode,
                payload: JSON.stringify(prompt.payload),
              });
              router.push(`${NEW_TASK_PATH}?${params.toString()}`);
            }}
          />
        ) : (
          <Table
            data={tasks}
            columns={columns}
            getRowId={(row) => row.id}
            selectionBehavior="single-select"
            onRowClick={(row) => router.push(taskDetailPath(row.id))}
          />
        )}
      </SettingsLayouts.Body>

      {pendingDelete && (
        <ConfirmationModalLayout
          icon={SvgTrash}
          title={`Delete "${pendingDelete.name}"?`}
          description="This stops future runs and removes the task. Past run history (and the underlying sessions) will be preserved for audit."
          onClose={() => setPendingDelete(null)}
          submit={
            <Button
              variant="danger"
              prominence="primary"
              onClick={() => void handleDelete()}
              disabled={busyTaskId === pendingDelete.id}
              data-testid="confirm-delete-task"
            >
              {busyTaskId === pendingDelete.id ? "Deleting..." : "Delete"}
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
  const disabled = handlers.busyTaskId === task.id;
  return (
    <div className="flex items-center gap-0.5">
      <Tooltip tooltip="Delete" side="top">
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

// ---------------------------------------------------------------------------
// Empty state
// ---------------------------------------------------------------------------

interface EmptyStateProps {
  onSelectStarter: (prompt: (typeof STARTER_PROMPTS)[number]) => void;
}

function EmptyState({ onSelectStarter }: EmptyStateProps) {
  return (
    <Section gap={1}>
      <div className="flex flex-col items-center text-center py-6 gap-2">
        <SvgClock size={48} className="text-text-03" />
        <Text headingH2 text05>
          Hand Craft a recurring job
        </Text>
        <Text mainUiBody text03 className="max-w-xl">
          Save a prompt + schedule and Craft will run it on a timer. Each fire
          creates a fresh session you can open from this page.
        </Text>
        <div className="pt-2">
          <Button
            variant="default"
            prominence="primary"
            icon={SvgPlus}
            href={NEW_TASK_PATH}
          >
            Create scheduled task
          </Button>
        </div>
      </div>
      <Text mainUiAction text05>
        Or start from a template:
      </Text>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {STARTER_PROMPTS.map((starter) => (
          <button
            key={starter.title}
            type="button"
            onClick={() => onSelectStarter(starter)}
            className="text-left"
            data-testid={`starter-${starter.title}`}
          >
            <Card>
              <Text mainUiAction text05>
                {starter.title}
              </Text>
              <Text secondaryBody text03>
                {starter.prompt}
              </Text>
            </Card>
          </button>
        ))}
      </div>
    </Section>
  );
}
