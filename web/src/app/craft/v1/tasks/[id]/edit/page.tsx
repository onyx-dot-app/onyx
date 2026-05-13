"use client";

import { useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import useSWR from "swr";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { SvgClock } from "@opal/icons";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import Text from "@/refresh-components/texts/Text";
import ScheduleTaskForm, {
  type ScheduleTaskFormInitial,
} from "@/app/craft/v1/tasks/components/ScheduleTaskForm";
import type { ScheduledTaskDetail } from "@/app/craft/v1/tasks/interfaces";
import { TASKS_PATH, taskDetailPath } from "@/app/craft/v1/tasks/constants";
import { decodeCronToPayload } from "@/app/craft/v1/tasks/schedule";
import { getBrowserTimezone } from "@/app/craft/v1/tasks/utils";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";

export default function EditScheduledTaskPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const taskId = params?.id;

  const { data, error, isLoading } = useSWR<ScheduledTaskDetail>(
    taskId ? SWR_KEYS.scheduledTask(taskId) : null,
    errorHandlingFetcher,
    { revalidateOnFocus: false }
  );

  const handleBack = useCallback(() => {
    if (taskId) router.push(taskDetailPath(taskId));
    else router.push(TASKS_PATH);
  }, [router, taskId]);

  if (!taskId) {
    return (
      <SettingsLayouts.Root width="lg">
        <SettingsLayouts.Header
          icon={SvgClock}
          title="Edit scheduled task"
          backButton
          onBack={handleBack}
        />
        <SettingsLayouts.Body>
          <Text mainUiBody text03>
            Missing task id.
          </Text>
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    );
  }

  return (
    <SettingsLayouts.Root width="lg">
      <SettingsLayouts.Header
        icon={SvgClock}
        title={data ? `Edit "${data.name}"` : "Edit scheduled task"}
        backButton
        onBack={handleBack}
      />
      <SettingsLayouts.Body>
        {isLoading ? (
          <div className="flex justify-center py-12">
            <SimpleLoader className="h-6 w-6" />
          </div>
        ) : error || !data ? (
          <Text mainUiBody text03>
            Failed to load scheduled task.
          </Text>
        ) : (
          <ScheduleTaskForm initial={toFormInitial(data)} isEdit />
        )}
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}

function toFormInitial(detail: ScheduledTaskDetail): ScheduleTaskFormInitial {
  // The backend stores cron + editor_mode but not editor_payload, so we
  // re-derive the editor-friendly payload from the cron expression. If the
  // cron can't be decoded back into the chosen mode (rare, e.g. someone
  // hand-edited via the API), we fall back to ``advanced`` mode so the user
  // sees the raw expression.
  const { mode, payload } = decodeCronToPayload(
    detail.editor_mode,
    detail.cron_expression
  );
  return {
    taskId: detail.id,
    name: detail.name,
    prompt: detail.prompt,
    mode,
    payload,
    timezone: detail.timezone || getBrowserTimezone(),
  };
}
