"use client";

import { useCallback, useMemo } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { SvgClock } from "@opal/icons";
import ScheduleTaskForm, {
  defaultFormInitial,
  type ScheduleTaskFormInitial,
} from "@/app/craft/v1/tasks/components/ScheduleTaskForm";
import type {
  EditorMode,
  EditorPayload,
} from "@/app/craft/v1/tasks/interfaces";
import { TASKS_PATH } from "@/app/craft/v1/tasks/constants";
import { getBrowserTimezone } from "@/app/craft/v1/tasks/utils";

const VALID_MODES: ReadonlySet<EditorMode> = new Set<EditorMode>([
  "interval",
  "daily_weekly",
  "advanced",
]);

export default function NewScheduledTaskPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const handleBack = useCallback(() => {
    router.push(TASKS_PATH);
  }, [router]);

  const initial: ScheduleTaskFormInitial = useMemo(() => {
    const base = defaultFormInitial();
    const starter = searchParams?.get("starter") ?? null;
    const promptParam = searchParams?.get("prompt") ?? null;
    const modeParam = searchParams?.get("mode") ?? null;
    const payloadParam = searchParams?.get("payload") ?? null;

    let mode: EditorMode = base.mode;
    if (modeParam && VALID_MODES.has(modeParam as EditorMode)) {
      mode = modeParam as EditorMode;
    }

    let payload: EditorPayload = base.payload;
    if (payloadParam) {
      try {
        const parsed = JSON.parse(payloadParam) as EditorPayload;
        payload = parsed;
      } catch {
        // ignore — fall back to defaults
      }
    }

    return {
      ...base,
      name: starter ?? "",
      prompt: promptParam ?? "",
      mode,
      payload,
      timezone: getBrowserTimezone(),
    };
  }, [searchParams]);

  return (
    <SettingsLayouts.Root width="lg">
      <SettingsLayouts.Header
        icon={SvgClock}
        title="New scheduled task"
        description="Save a prompt + schedule. Craft will run it on a timer."
        backButton
        onBack={handleBack}
      />
      <SettingsLayouts.Body>
        <ScheduleTaskForm initial={initial} isEdit={false} />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
