"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Button, Divider, InputTypeIn, Text } from "@opal/components";
import InputTextArea from "@/refresh-components/inputs/InputTextArea";
import { Disabled } from "@opal/core";
import { SettingsLayouts, InputVertical } from "@opal/layouts";
import * as GeneralLayouts from "@/layouts/general-layouts";
import { toast } from "@/hooks/useToast";
import { SvgClock } from "@opal/icons";
import ScheduleEditor from "@/app/craft/v1/tasks/components/ScheduleEditor";
import PreApprovalPicker from "@/app/craft/v1/tasks/components/PreApprovalPicker";
import {
  compileLocalPayloadToUtcCron,
  localPayloadToUtcPayload,
} from "@/app/craft/v1/tasks/schedule";
import EntryPickerPopover from "@/sections/input/EntryPickerPopover";
import useUserSkills from "@/hooks/useUserSkills";
import useUserExternalApps from "@/hooks/useUserExternalApps";
import {
  detectSlashTrigger,
  toPickerSections,
  type PickerEntry,
} from "@/lib/skills/picker";
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
import { TASKS_PATH, taskDetailPath } from "@/app/craft/v1/tasks/constants";

export interface ScheduleTaskFormInitial {
  /** ``null`` for create. */
  taskId: string | null;
  name: string;
  prompt: string;
  mode: EditorMode;
  payload: EditorPayload;
  preApprovedAppIds: number[];
}

interface ScheduleTaskFormProps {
  initial: ScheduleTaskFormInitial;
  /** Used to title the page / customize the submit button. */
  isEdit: boolean;
  /** Title rendered in the settings header. */
  title: string;
  /** Optional sub-title rendered beneath the header title. */
  description?: string;
  /** Invoked when the back button is pressed. */
  onBack: () => void;
}

export default function ScheduleTaskForm({
  initial,
  isEdit,
  title,
  description,
  onBack,
}: ScheduleTaskFormProps) {
  const router = useRouter();
  const [name, setName] = useState(initial.name);
  const [prompt, setPrompt] = useState(initial.prompt);
  const [mode, setMode] = useState<EditorMode>(initial.mode);
  const [payload, setPayload] = useState<EditorPayload>(initial.payload);
  const [preApprovedAppIds, setPreApprovedAppIds] = useState<number[]>(
    initial.preApprovedAppIds
  );
  const [saving, setSaving] = useState(false);
  const [nameTouched, setNameTouched] = useState(false);
  const [promptTouched, setPromptTouched] = useState(false);

  const promptTextareaRef = useRef<HTMLTextAreaElement>(null);
  const { data: skillsData } = useUserSkills();
  const { data: externalAppsData } = useUserExternalApps();
  const pickerSections = useMemo(
    () => toPickerSections(skillsData, externalAppsData),
    [skillsData, externalAppsData]
  );
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
    (entry: PickerEntry) => {
      if (entry.kind === "app" && !entry.authenticated) {
        setSkillPicker((s) => ({ ...s, open: false }));
        router.push(`/craft/v1/apps?connect=${entry.slug}`);
        return;
      }
      setSkillPicker((prev) => {
        if (!prev.open) return prev;
        const replacement = `/${entry.slug} `;
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
    [prompt, router]
  );

  const compiled = compileLocalPayloadToUtcCron(mode, payload);

  const trimmedName = name.trim();
  const trimmedPrompt = prompt.trim();

  // Validation states. These gate submission regardless of interaction, but
  // are only surfaced inline once the user has touched (blurred) the field so
  // a pristine form doesn't render red on load.
  const nameError = trimmedName.length === 0 ? "名称为必填项。" : null;
  const promptError = trimmedPrompt.length === 0 ? "提示词为必填项。" : null;
  const scheduleError = !compiled.ok ? compiled.error : null;

  const shownNameError = nameTouched ? nameError : null;
  const shownPromptError = promptTouched ? promptError : null;

  const canSubmit = !nameError && !promptError && !scheduleError && !saving;

  // Reason a submit button is blocked, surfaced via the `Disabled` wrapper's
  // tooltip. A natively-disabled <button> is inert and never fires hover
  // events, so the tooltip must live on the (interactive) wrapper instead.
  const disabledReason = saving
    ? "正在保存..."
    : (nameError ?? promptError ?? scheduleError ?? undefined);

  const submit = useCallback(
    async (runImmediately: boolean) => {
      if (!compiled.ok) return; // validation should already block, but typescript needs this
      setSaving(true);
      try {
        const storagePayload = localPayloadToUtcPayload(mode, payload);
        if (isEdit && initial.taskId) {
          const body: ScheduledTaskPatchBody = {
            name: trimmedName,
            prompt: trimmedPrompt,
            editor_mode: mode,
            editor_payload: storagePayload,
            pre_approved_app_ids: preApprovedAppIds,
          };
          const updated: ScheduledTaskDetail = await updateScheduledTask(
            initial.taskId,
            body
          );
          toast.success("定时任务已更新。");
          router.push(taskDetailPath(updated.id));
        } else {
          const body: ScheduledTaskCreateBody = {
            name: trimmedName,
            prompt: trimmedPrompt,
            editor_mode: mode,
            editor_payload: storagePayload,
            run_immediately: runImmediately,
            pre_approved_app_ids: preApprovedAppIds,
          };
          await createScheduledTask(body);
          toast.success(
            runImmediately
              ? "定时任务已创建并加入队列。"
              : "定时任务已创建。"
          );
          router.push(TASKS_PATH);
        }
      } catch (err) {
        toast.error(
          err instanceof Error ? err.message : "保存定时任务失败"
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
      preApprovedAppIds,
      router,
      trimmedName,
      trimmedPrompt,
    ]
  );

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgClock}
        title={title}
        description={description}
        backButton={onBack}
        divider
        rightChildren={
          <div className="flex gap-2 self-start">
            <Button
              variant="default"
              prominence="secondary"
              type="button"
              onClick={() => router.push(TASKS_PATH)}
              disabled={saving}
            >
              取消
            </Button>
            {!isEdit && (
              <Disabled
                disabled={!canSubmit}
                tooltip={disabledReason}
                tooltipSide="bottom"
              >
                <Button
                  variant="default"
                  prominence="secondary"
                  type="button"
                  disabled={!canSubmit}
                  onClick={() => void submit(true)}
                  data-testid="save-and-run-now"
                >
                  保存并立即运行
                </Button>
              </Disabled>
            )}
            <Disabled
              disabled={!canSubmit}
              tooltip={disabledReason}
              tooltipSide="bottom"
            >
              <Button
                variant="default"
                prominence="primary"
                type="button"
                disabled={!canSubmit}
                onClick={() => void submit(false)}
                data-testid="save-task"
              >
                {isEdit ? "保存更改" : "保存"}
              </Button>
            </Disabled>
          </div>
        }
      />

      <SettingsLayouts.Body>
        <GeneralLayouts.Section>
          <InputVertical withLabel title="名称">
            <InputTypeIn
              value={name}
              onChange={(e) => setName(e.target.value)}
              onBlur={() => setNameTouched(true)}
              placeholder="例如：每周客户升级问题摘要"
              data-testid="task-name-input"
              variant={shownNameError ? "error" : undefined}
            />
            {shownNameError && (
              <Text font="secondary-body" color="status-error-05">
                {shownNameError}
              </Text>
            )}
          </InputVertical>

          <InputVertical
            withLabel
            title="提示词"
            description="每次任务触发时，都会将此消息发送给 Glomi 创作。"
          >
            <InputTextArea
              ref={promptTextareaRef}
              value={prompt}
              onChange={handlePromptChange}
              onKeyUp={handlePromptCursorChange}
              onClick={handlePromptCursorChange}
              onBlur={() => setPromptTouched(true)}
              placeholder="描述 Glomi 创作每次运行时应该做什么..."
              rows={6}
              autoResize
              maxRows={12}
              data-testid="task-prompt-input"
              variant={shownPromptError ? "error" : undefined}
            />
            <EntryPickerPopover
              open={skillPicker.open}
              anchorRect={skillPicker.anchorRect}
              query={skillPicker.query}
              sections={pickerSections}
              onSelect={handleSkillPickerSelect}
              onClose={closeSkillPicker}
            />
            {shownPromptError && (
              <Text font="secondary-body" color="status-error-05">
                {shownPromptError}
              </Text>
            )}
          </InputVertical>
        </GeneralLayouts.Section>

        <Divider paddingParallel="fit" paddingPerpendicular="fit" />

        <GeneralLayouts.Section>
          <InputVertical title="计划">
            <ScheduleEditor
              mode={mode}
              onModeChange={setMode}
              payload={payload}
              onPayloadChange={setPayload}
              error={scheduleError}
            />
          </InputVertical>
        </GeneralLayouts.Section>

        <Divider paddingParallel="fit" paddingPerpendicular="fit" />

        <GeneralLayouts.Section>
          <InputVertical
            title="预先批准的应用"
            description="选中的应用可在任务自动运行时直接执行，无需暂停等待批准。注意：未预先批准的应用会在运行中暂停并请求你的批准；如果你未批准操作请求，本次运行可能会停滞或失败。"
          >
            <PreApprovalPicker
              selectedIds={preApprovedAppIds}
              onChange={setPreApprovedAppIds}
            />
          </InputVertical>
        </GeneralLayouts.Section>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}

export function defaultFormInitial(): ScheduleTaskFormInitial {
  return {
    taskId: null,
    name: "",
    prompt: "",
    mode: "interval",
    payload: { unit: "hours", every: 1 },
    preApprovedAppIds: [],
  };
}
