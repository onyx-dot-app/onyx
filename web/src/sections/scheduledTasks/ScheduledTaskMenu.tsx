"use client";

import { useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { mutate } from "swr";
import { Button, useCreateModal } from "@opal/components";
import { ConfirmationModalLayout, toast } from "@opal/layouts";
import {
  SvgEdit,
  SvgPauseCircle,
  SvgPlayCircle,
  SvgTrash,
  SvgZap,
} from "@opal/icons";
import { useNavigation } from "@opal/navigation";
import { revalidateChatScheduledRunViews } from "@/lib/scheduledTasks/hooks";
import { editScheduledTaskHref } from "@/lib/scheduledTasks/paths";
import {
  deleteScheduledTask,
  runScheduledTaskNow,
  updateScheduledTask,
} from "@/lib/scheduledTasks/svc";
import type { ScheduledTaskListItem } from "@/lib/scheduledTasks/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import { CustomizeRowActions } from "@/sections/customize/CustomizeList";

/** Run once, Pause or Resume, and Delete with its confirmation. */
export function useScheduledTaskActions(
  task: ScheduledTaskListItem | undefined,
  onDeleted?: () => void
) {
  const t = useTranslations("scheduledTasks.actions");
  const [busy, setBusy] = useState(false);
  const deleteModal = useCreateModal();

  async function act(work: () => Promise<string>, failure: string) {
    setBusy(true);
    try {
      toast.success(await work());
    } catch (err) {
      toast.error(err instanceof Error ? err.message : failure);
    } finally {
      setBusy(false);
    }
  }

  function runNow() {
    if (!task) return;
    void act(async () => {
      await runScheduledTaskNow(task.id);
      await revalidateChatScheduledRunViews(task.id);
      return t("toasts.runQueued", { name: task.name });
    }, t("toasts.runFailed"));
  }

  function toggleStatus() {
    if (!task) return;
    const next = task.status === "ACTIVE" ? "PAUSED" : "ACTIVE";
    void act(async () => {
      await updateScheduledTask(task.id, { status: next });
      await Promise.all([
        mutate(SWR_KEYS.chatScheduledTasks),
        mutate(SWR_KEYS.chatScheduledTask(task.id)),
      ]);
      return t(next === "ACTIVE" ? "toasts.resumed" : "toasts.paused");
    }, t("toasts.statusFailed"));
  }

  function confirmDelete() {
    if (!task) return;
    void act(async () => {
      await deleteScheduledTask(task.id);
      deleteModal.toggle(false);
      await Promise.all([
        mutate(SWR_KEYS.chatScheduledTasks),
        mutate(SWR_KEYS.chatScheduledTasksUnviewedCount),
      ]);
      onDeleted?.();
      return t("toasts.deleted", { name: task.name });
    }, t("toasts.deleteFailed"));
  }

  const modal: ReactNode = (
    <deleteModal.Provider>
      {task && (
        <ConfirmationModalLayout
          icon={SvgTrash}
          title={t("confirmDelete.title", { name: task.name })}
          description={t("confirmDelete.description")}
          onClose={() => deleteModal.toggle(false)}
          submit={
            <Button
              variant="danger"
              disabled={busy}
              onClick={confirmDelete}
              data-testid="confirm-delete-scheduled-task"
            >
              {t("confirmDelete.submit")}
            </Button>
          }
        />
      )}
    </deleteModal.Provider>
  );

  return {
    busy,
    runNow,
    toggleStatus,
    requestDelete: () => deleteModal.toggle(true),
    modal,
  };
}

interface ScheduledTaskMenuProps {
  task: ScheduledTaskListItem;
}

export default function ScheduledTaskMenu({ task }: ScheduledTaskMenuProps) {
  const t = useTranslations("scheduledTasks.actions");
  const navigation = useNavigation();
  const actions = useScheduledTaskActions(task);
  return (
    <>
      <CustomizeRowActions
        menuLabel={t("menu", { name: task.name })}
        menu={[
          {
            kind: "action",
            id: "run",
            icon: SvgZap,
            title: t("runNow"),
            disabled: actions.busy,
            onSelect: actions.runNow,
          },
          {
            kind: "action",
            id: "toggle",
            icon: task.status === "ACTIVE" ? SvgPauseCircle : SvgPlayCircle,
            title: t(task.status === "ACTIVE" ? "pause" : "resume"),
            disabled: actions.busy,
            onSelect: actions.toggleStatus,
          },
          {
            kind: "action",
            id: "edit",
            icon: SvgEdit,
            title: t("edit"),
            onSelect: () => navigation.go(editScheduledTaskHref(task.id)),
          },
          {
            kind: "action",
            id: "delete",
            icon: SvgTrash,
            title: t("delete"),
            danger: true,
            disabled: actions.busy,
            onSelect: actions.requestDelete,
          },
        ]}
      />
      {actions.modal}
    </>
  );
}
