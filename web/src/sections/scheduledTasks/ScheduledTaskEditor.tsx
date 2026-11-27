"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import useSWR, { mutate } from "swr";
import { useTranslations } from "next-intl";
import {
  Button,
  Divider,
  InputTextArea,
  InputTypeIn,
  Text,
} from "@opal/components";
import { InputVertical, Section, SettingsLayouts, toast } from "@opal/layouts";
import { SvgClock } from "@opal/icons";
import { useNavigation } from "@opal/navigation";
import ScheduleEditor from "@/app/craft/v1/tasks/components/ScheduleEditor";
import TaskActionPolicies from "@/app/craft/v1/tasks/components/TaskActionPolicies";
import {
  compileLocalPayloadToUtcCron,
  decodeUtcCronToLocalPayload,
  localPayloadToUtcPayload,
} from "@/app/craft/v1/tasks/schedule";
import type {
  EditorMode,
  EditorPayload,
  TaskIntegrationLink,
} from "@/app/craft/v1/tasks/types";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { revalidateScheduledRunViews } from "@/lib/scheduledTasks/hooks";
import {
  SCHEDULED_TASKS_PATH,
  scheduledTaskHref,
} from "@/lib/scheduledTasks/paths";
import {
  createScheduledTask,
  updateScheduledTask,
} from "@/lib/scheduledTasks/svc";
import type { ScheduledTaskDetail } from "@/lib/scheduledTasks/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import { BackLink } from "@/sections/customize/CustomizeDetailLayout";
import UnsavedChangesModal from "@/sections/modals/UnsavedChangesModal";
import useUnsavedChangesGuard from "@/hooks/useUnsavedChangesGuard";

// The limits of the scheduled-task API.
const NAME_MAX_CHARS = 200;
const PROMPT_MAX_CHARS = 20_000;

interface ScheduledTaskEditorProps {
  /** Absent for a new task. */
  taskId?: string;
}

/** Counts code points after trimming, as the server does. */
function charCount(text: string): number {
  return Array.from(text.trim()).length;
}

export default function ScheduledTaskEditor({
  taskId,
}: ScheduledTaskEditorProps) {
  const t = useTranslations("scheduledTasks.editor");
  const { data, error, isLoading } = useSWR<ScheduledTaskDetail>(
    taskId ? SWR_KEYS.chatScheduledTask(taskId) : null,
    errorHandlingFetcher,
    { revalidateOnFocus: false }
  );
  if (taskId && !data)
    return (
      <SettingsLayouts.Root
        loading={isLoading}
        error={error ? t("loadFailed") : false}
      >
        <SettingsLayouts.Header icon={SvgClock} title={t("editTitle")} />
        <SettingsLayouts.Body />
      </SettingsLayouts.Root>
    );
  return <TaskForm key={data?.id ?? "new"} task={data} />;
}

interface TaskFormProps {
  task: ScheduledTaskDetail | undefined;
}

function TaskForm({ task }: TaskFormProps) {
  const t = useTranslations("scheduledTasks.editor");
  const tScheduleEditor = useTranslations("craft.tasks.scheduleEditor");
  const navigation = useNavigation();
  // Daylight saving moves the local time of a stored UTC time. Read and
  // write it at the date of the next fire, so a save keeps the schedule.
  const [referenceDate] = useState(() =>
    task?.next_run_at ? new Date(task.next_run_at) : new Date()
  );
  const [initial] = useState<{ mode: EditorMode; payload: EditorPayload }>(
    () =>
      task
        ? decodeUtcCronToLocalPayload(
            task.editor_mode,
            task.cron_expression,
            referenceDate
          )
        : { mode: "interval", payload: { unit: "hours", every: 1 } }
  );
  const [name, setName] = useState(task?.name ?? "");
  const [prompt, setPrompt] = useState(task?.prompt ?? "");
  const [mode, setMode] = useState<EditorMode>(initial.mode);
  const [payload, setPayload] = useState<EditorPayload>(initial.payload);
  const [integrations, setIntegrations] = useState<
    TaskIntegrationLink[] | null
  >(null);
  // The integrations as first loaded, to tell whether the user changed them.
  const [initialIntegrations, setInitialIntegrations] = useState<
    TaskIntegrationLink[] | null
  >(null);
  // The last payload of each mode, so switching modes and back keeps it.
  const payloadByMode = useRef<Partial<Record<EditorMode, EditorPayload>>>({
    [initial.mode]: initial.payload,
  });
  // A mode switch restored a payload; the editor's default for the new mode
  // that follows in the same event must not replace it.
  const restoredPayload = useRef(false);
  const [touched, setTouched] = useState({ name: false, prompt: false });
  const [saving, setSaving] = useState(false);
  // State updates land on the next render; the ref stops a second click
  // in the same frame from sending a second save.
  const savingRef = useRef(false);

  const compiled = compileLocalPayloadToUtcCron(mode, payload, referenceDate);
  const nameError = !name.trim()
    ? t("errors.nameRequired")
    : charCount(name) > NAME_MAX_CHARS
      ? t("errors.tooLong", { max: NAME_MAX_CHARS })
      : null;
  const promptError = !prompt.trim()
    ? t("errors.promptRequired")
    : charCount(prompt) > PROMPT_MAX_CHARS &&
        prompt.trim() !== task?.prompt.trim()
      ? t("errors.tooLong", { max: PROMPT_MAX_CHARS })
      : null;
  const dirty =
    name !== (task?.name ?? "") ||
    prompt !== (task?.prompt ?? "") ||
    mode !== initial.mode ||
    JSON.stringify(payload) !== JSON.stringify(initial.payload) ||
    JSON.stringify(integrations) !== JSON.stringify(initialIntegrations);
  const formSnapshot = JSON.stringify([
    name,
    prompt,
    mode,
    payload,
    integrations,
  ]);
  const latestSnapshot = useRef(formSnapshot);
  useEffect(() => {
    latestSnapshot.current = formSnapshot;
  }, [formSnapshot]);
  // The form as it was sent. Edits made after it stay guarded.
  const [savedSnapshot, setSavedSnapshot] = useState<string | null>(null);
  const unsaved = useUnsavedChangesGuard({
    isDirty: dirty && formSnapshot !== savedSnapshot,
  });

  useEffect(() => {
    restoredPayload.current = false;
  }, [mode]);

  function changeMode(next: EditorMode) {
    payloadByMode.current[mode] = payload;
    setMode(next);
    const remembered = payloadByMode.current[next];
    if (remembered) {
      setPayload(remembered);
      restoredPayload.current = true;
    }
  }

  function changePayload(next: EditorPayload) {
    if (restoredPayload.current) return;
    setPayload(next);
  }

  const changeIntegrations = useCallback((next: TaskIntegrationLink[]) => {
    setIntegrations(next);
    setInitialIntegrations((was) => was ?? next);
  }, []);
  const canSave =
    !nameError &&
    !promptError &&
    compiled.ok &&
    integrations !== null &&
    !saving;

  async function save(runNow: boolean) {
    if (!canSave || integrations === null || savingRef.current) return;
    savingRef.current = true;
    setSaving(true);
    const submitted = formSnapshot;
    setSavedSnapshot(submitted);
    const fields = {
      name: name.trim(),
      prompt: prompt.trim(),
      editor_mode: mode,
      editor_payload: localPayloadToUtcPayload(mode, payload, referenceDate),
      integrations,
    };
    try {
      const saved = task
        ? await updateScheduledTask(task.id, fields)
        : await createScheduledTask({ ...fields, run_immediately: runNow });
      await Promise.all([
        mutate(SWR_KEYS.chatScheduledTask(saved.id), saved, {
          revalidate: false,
        }),
        mutate(SWR_KEYS.chatScheduledTaskActionPolicies(saved.id)),
        revalidateScheduledRunViews(saved.id),
      ]);
      toast.success(
        task
          ? t("toasts.updated")
          : t(runNow ? "toasts.createdAndRun" : "toasts.created")
      );
      const leave = () => navigation.go(scheduledTaskHref(saved.id));
      if (latestSnapshot.current === submitted) {
        leave();
        return;
      }
      savingRef.current = false;
      setSaving(false);
      unsaved.requestLeave(leave);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("toasts.saveFailed"));
      savingRef.current = false;
      setSaving(false);
      setSavedSnapshot(null);
    }
  }

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgClock}
        title={task ? t("editTitle") : t("newTitle")}
        description={t("description")}
        back={
          <BackLink
            to={task ? scheduledTaskHref(task.id) : SCHEDULED_TASKS_PATH}
            label={t("back")}
          />
        }
        divider
        actions={[
          ...(task
            ? []
            : [
                <Button
                  key="run"
                  prominence="secondary"
                  disabled={!canSave}
                  onClick={() => void save(true)}
                  data-testid="save-and-run-scheduled-task"
                >
                  {t("saveAndRun")}
                </Button>,
              ]),
          <Button
            key="save"
            disabled={!canSave}
            onClick={() => void save(false)}
            data-testid="save-scheduled-task"
          >
            {t("save")}
          </Button>,
        ]}
      />
      <SettingsLayouts.Body>
        <Section height="auto" alignItems="stretch">
          <InputVertical withLabel title={t("fields.name.label")}>
            <InputTypeIn
              value={name}
              onChange={(event) => setName(event.target.value)}
              onBlur={() => setTouched((was) => ({ ...was, name: true }))}
              placeholder={t("fields.name.placeholder")}
              variant={touched.name && nameError ? "error" : undefined}
              data-testid="scheduled-task-name"
            />
            {touched.name && nameError && (
              <Text as="p" font="secondary-body" color="status-error-05">
                {nameError}
              </Text>
            )}
          </InputVertical>
          <InputVertical
            withLabel
            title={t("fields.prompt.label")}
            description={t("fields.prompt.description")}
          >
            <InputTextArea
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              onBlur={() => setTouched((was) => ({ ...was, prompt: true }))}
              placeholder={t("fields.prompt.placeholder")}
              rows={6}
              autoResize
              maxRows={12}
              variant={touched.prompt && promptError ? "error" : undefined}
              data-testid="scheduled-task-prompt"
            />
            {touched.prompt && promptError && (
              <Text as="p" font="secondary-body" color="status-error-05">
                {promptError}
              </Text>
            )}
          </InputVertical>
        </Section>
        <Divider paddingParallel={0} paddingPerpendicular={0} />
        <InputVertical title={t("fields.schedule.label")}>
          <ScheduleEditor
            mode={mode}
            onModeChange={changeMode}
            payload={payload}
            onPayloadChange={changePayload}
            error={
              compiled.ok ? null : tScheduleEditor(`errors.${compiled.error}`)
            }
            allowAdvanced
            referenceDate={referenceDate}
          />
        </InputVertical>
        <Divider paddingParallel={0} paddingPerpendicular={0} />
        <TaskActionPolicies
          taskId={task?.id ?? null}
          value={integrations}
          onChange={changeIntegrations}
          url={
            task
              ? SWR_KEYS.chatScheduledTaskActionPolicies(task.id)
              : SWR_KEYS.chatScheduledTaskCatalog
          }
        />
      </SettingsLayouts.Body>
      <UnsavedChangesModal
        open={unsaved.confirmationOpen}
        onCancel={unsaved.cancelLeave}
        onDiscard={unsaved.discardAndLeave}
      />
    </SettingsLayouts.Root>
  );
}
