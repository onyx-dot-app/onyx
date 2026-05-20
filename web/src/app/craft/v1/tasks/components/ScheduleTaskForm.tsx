"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Text from "@/refresh-components/texts/Text";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import InputTextArea from "@/refresh-components/inputs/InputTextArea";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import { Button, Divider } from "@opal/components";
import Card from "@/refresh-components/cards/Card";
import { Section } from "@/layouts/general-layouts";
import { toast } from "@/hooks/useToast";
import { SvgClock } from "@opal/icons";
import ScheduleEditor from "@/app/craft/v1/tasks/components/ScheduleEditor";
import { compileToCron, computeNextRuns } from "@/app/craft/v1/tasks/schedule";
import SkillPickerPopover from "@/sections/input/SkillPickerPopover";
import useUserSkills from "@/hooks/useUserSkills";
import { detectSlashTrigger, toPickerSkills } from "@/lib/skills/picker";
import type {
  EditorMode,
  EditorPayload,
  ScheduledTaskCreateBody,
  ScheduledTaskDetail,
  ScheduledTaskPatchBody,
} from "@/app/craft/v1/tasks/interfaces";
import {
  createScheduledTask,
  updateScheduledTask,
} from "@/app/craft/v1/tasks/api";
import {
  formatAbsolute,
  formatRelativeShort,
  getBrowserTimezone,
  getCommonTimezones,
} from "@/app/craft/v1/tasks/utils";
import { TASKS_PATH, taskDetailPath } from "@/app/craft/v1/tasks/constants";

export interface ScheduleTaskFormInitial {
  /** ``null`` for create. */
  taskId: string | null;
  name: string;
  prompt: string;
  mode: EditorMode;
  payload: EditorPayload;
  timezone: string;
}

interface ScheduleTaskFormProps {
  initial: ScheduleTaskFormInitial;
  /** Used to title the page / customize the submit button. */
  isEdit: boolean;
}

export default function ScheduleTaskForm({
  initial,
  isEdit,
}: ScheduleTaskFormProps) {
  const router = useRouter();
  const [name, setName] = useState(initial.name);
  const [prompt, setPrompt] = useState(initial.prompt);
  const [mode, setMode] = useState<EditorMode>(initial.mode);
  const [payload, setPayload] = useState<EditorPayload>(initial.payload);
  const [timezone, setTimezone] = useState(initial.timezone);
  const [saving, setSaving] = useState(false);

  // `/` skill picker state for the prompt field. Scoped to the trigger
  // owner's accessible skills (same access query as `GET /skills`).
  const promptTextareaRef = useRef<HTMLTextAreaElement>(null);
  const { data: skillsData } = useUserSkills();
  const pickerSkills = useMemo(() => toPickerSkills(skillsData), [skillsData]);
  const [skillPicker, setSkillPicker] = useState<{
    open: boolean;
    anchorRect: DOMRect | null;
    query: string;
    slashIndex: number;
  }>({ open: false, anchorRect: null, query: "", slashIndex: -1 });

  const evaluateSkillPicker = useCallback((value: string, cursor: number) => {
    const textBefore = value.slice(0, cursor);
    const trigger = detectSlashTrigger(textBefore);
    if (!trigger) {
      setSkillPicker((s) => (s.open ? { ...s, open: false } : s));
      return;
    }
    const anchorRect =
      promptTextareaRef.current?.getBoundingClientRect() ?? null;
    setSkillPicker({
      open: true,
      anchorRect,
      query: trigger.query,
      slashIndex: trigger.slashIndex,
    });
  }, []);

  const handlePromptChange = useCallback(
    (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      const value = e.target.value;
      setPrompt(value);
      evaluateSkillPicker(value, e.target.selectionStart ?? value.length);
    },
    [evaluateSkillPicker]
  );

  const handlePromptCursorChange = useCallback(
    (e: React.SyntheticEvent<HTMLTextAreaElement>) => {
      const target = e.currentTarget;
      evaluateSkillPicker(target.value, target.selectionStart ?? 0);
    },
    [evaluateSkillPicker]
  );

  const closeSkillPicker = useCallback(() => {
    setSkillPicker((s) => ({ ...s, open: false }));
  }, []);

  const handleSkillPickerSelect = useCallback(
    (slug: string) => {
      setSkillPicker((prev) => {
        if (!prev.open) return prev;
        const replacement = `/${slug} `;
        const newPrompt =
          prompt.slice(0, prev.slashIndex) +
          replacement +
          prompt.slice(prev.slashIndex + 1 + prev.query.length);
        setPrompt(newPrompt);

        const cursorPos = prev.slashIndex + replacement.length;
        const textarea = promptTextareaRef.current;
        if (textarea) {
          requestAnimationFrame(() => {
            textarea.focus();
            textarea.setSelectionRange(cursorPos, cursorPos);
          });
        }
        return { ...prev, open: false };
      });
    },
    [prompt]
  );

  const timezones = useMemo(() => getCommonTimezones(), []);
  const compiled = compileToCron(mode, payload);

  const nextRuns = useMemo(() => {
    if (!compiled.ok) return [];
    return computeNextRuns(compiled.cron, timezone, 3);
  }, [compiled, timezone]);

  const trimmedName = name.trim();
  const trimmedPrompt = prompt.trim();

  // Validation states surfaced to the user.
  const nameError = trimmedName.length === 0 ? "Name is required." : null;
  const promptError = trimmedPrompt.length === 0 ? "Prompt is required." : null;
  const tzError = !timezone ? "Timezone is required." : null;
  const scheduleError = !compiled.ok ? compiled.error : null;

  const canSubmit =
    !nameError && !promptError && !tzError && !scheduleError && !saving;

  const submit = useCallback(
    async (runImmediately: boolean) => {
      if (!compiled.ok) return; // validation should already block, but typescript needs this
      setSaving(true);
      try {
        if (isEdit && initial.taskId) {
          const body: ScheduledTaskPatchBody = {
            name: trimmedName,
            prompt: trimmedPrompt,
            editor_mode: mode,
            editor_payload: payload,
            timezone,
          };
          const updated: ScheduledTaskDetail = await updateScheduledTask(
            initial.taskId,
            body
          );
          toast.success("Scheduled task updated.");
          router.push(taskDetailPath(updated.id));
        } else {
          const body: ScheduledTaskCreateBody = {
            name: trimmedName,
            prompt: trimmedPrompt,
            editor_mode: mode,
            editor_payload: payload,
            timezone,
            run_immediately: runImmediately,
          };
          await createScheduledTask(body);
          toast.success(
            runImmediately
              ? "Scheduled task created and queued."
              : "Scheduled task created."
          );
          router.push(TASKS_PATH);
        }
      } catch (err) {
        toast.error(
          err instanceof Error ? err.message : "Failed to save scheduled task"
        );
      } finally {
        setSaving(false);
      }
    },
    [
      compiled,
      isEdit,
      initial.taskId,
      mode,
      payload,
      router,
      timezone,
      trimmedName,
      trimmedPrompt,
    ]
  );

  return (
    <Section gap={1}>
      {/* Name */}
      <Card>
        <Text mainUiAction text05>
          Name
        </Text>
        <InputTypeIn
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Weekly customer escalations digest"
          data-testid="task-name-input"
          variant={nameError ? "error" : undefined}
        />
        {nameError && (
          <Text secondaryBody text03 className="text-status-error-05">
            {nameError}
          </Text>
        )}
      </Card>

      {/* Prompt */}
      <Card>
        <Text mainUiAction text05>
          Prompt
        </Text>
        <Text secondaryBody text03>
          This message is sent to Craft each time the task fires.
        </Text>
        <InputTextArea
          ref={promptTextareaRef}
          value={prompt}
          onChange={handlePromptChange}
          onKeyUp={handlePromptCursorChange}
          onClick={handlePromptCursorChange}
          placeholder="Describe what Craft should do on each run..."
          rows={6}
          autoResize
          maxRows={12}
          data-testid="task-prompt-input"
          variant={promptError ? "error" : undefined}
        />
        <SkillPickerPopover
          open={skillPicker.open}
          anchorRect={skillPicker.anchorRect}
          query={skillPicker.query}
          skills={pickerSkills}
          onSelect={handleSkillPickerSelect}
          onClose={closeSkillPicker}
        />
        {promptError && (
          <Text secondaryBody text03 className="text-status-error-05">
            {promptError}
          </Text>
        )}
      </Card>

      {/* Schedule */}
      <Card>
        <Text mainUiAction text05>
          Schedule
        </Text>
        <ScheduleEditor
          mode={mode}
          onModeChange={setMode}
          payload={payload}
          onPayloadChange={setPayload}
          error={scheduleError}
        />
        <Divider />
        <Text mainUiAction text05>
          Timezone
        </Text>
        <div className="w-full max-w-[28rem]">
          <InputSelect value={timezone} onValueChange={setTimezone}>
            <InputSelect.Trigger placeholder="Select a timezone..." />
            <InputSelect.Content>
              {timezones.map((tz) => (
                <InputSelect.Item key={tz} value={tz}>
                  {tz}
                </InputSelect.Item>
              ))}
            </InputSelect.Content>
          </InputSelect>
        </div>
        {tzError && (
          <Text secondaryBody text03 className="text-status-error-05">
            {tzError}
          </Text>
        )}
      </Card>

      {/* Next runs preview */}
      <Card>
        <div className="flex items-center gap-2">
          <SvgClock size={16} className="text-text-03" />
          <Text mainUiAction text05>
            Next 3 runs
          </Text>
        </div>
        {nextRuns.length === 0 ? (
          <Text secondaryBody text03>
            {scheduleError
              ? "Fix the schedule above to preview future fires."
              : "No upcoming fires for this expression."}
          </Text>
        ) : (
          <ul className="flex flex-col gap-1">
            {nextRuns.map((iso, idx) => (
              <li key={iso} className="flex flex-col">
                <Text mainUiBody text05>
                  {idx + 1}. {formatAbsolute(iso)}
                </Text>
                <Text secondaryBody text03>
                  {formatRelativeShort(iso)} ({timezone})
                </Text>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <div className="flex items-center gap-2 justify-end">
        <Button
          variant="default"
          prominence="secondary"
          onClick={() => router.push(TASKS_PATH)}
          disabled={saving}
        >
          Cancel
        </Button>
        {!isEdit && (
          <Button
            variant="default"
            prominence="secondary"
            disabled={!canSubmit}
            onClick={() => void submit(true)}
            data-testid="save-and-run-now"
          >
            Save and run now
          </Button>
        )}
        <Button
          variant="default"
          prominence="primary"
          disabled={!canSubmit}
          onClick={() => void submit(false)}
          data-testid="save-task"
        >
          {isEdit ? "Save changes" : "Save"}
        </Button>
      </div>
    </Section>
  );
}

export function defaultFormInitial(): ScheduleTaskFormInitial {
  return {
    taskId: null,
    name: "",
    prompt: "",
    mode: "interval",
    payload: { unit: "hours", every: 1 },
    timezone: getBrowserTimezone(),
  };
}
