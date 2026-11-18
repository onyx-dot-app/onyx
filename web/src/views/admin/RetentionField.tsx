"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Section } from "@opal/layouts";
import {
  Button,
  InputSingleSelect,
  InputTypeIn,
  Text,
  useCreateModal,
  type SelectOption,
} from "@opal/components";
import { SvgChevronDown, SvgRevert } from "@opal/icons";
import GenericConfirmModal from "@/sections/modals/GenericConfirmModal";
import { useTierAtLeast, useTierLockedOptions } from "@/lib/tiers/hooks";
import { Tier } from "@/lib/tiers/types";

// Retention presets offered directly in the dropdown, matching the Figma
// design. Any other (positive) value is surfaced via "Custom Retention". The
// backend stores maximum_chat_retention_days as a free-form number of days, so
// these are purely UI (365 is labelled "1 year").
const RETENTION_PRESET_DAYS = [7, 30, 60, 90, 365] as const;
// FE-only guard: the backend imposes no upper bound, so cap absurd input.
const MAX_RETENTION_DAYS = 36500; // ~100 years
const CUSTOM_RETENTION_VALUE = "custom";
const FOREVER_RETENTION_VALUE = "forever";

// Pure predicate — lives at module scope so it can be referenced inside
// useEffect without an exhaustive-deps suppression.
const valueIsCustomRetention = (v: number | null): v is number =>
  v !== null && !RETENTION_PRESET_DAYS.some((days) => days === v);

// True only when the string is one or more digits within the allowed range.
// parseInt alone would silently accept "1.5" → 1 or "7abc" → 7, so guard with
// a digits-only check before persisting.
const isValidCustomRetention = (raw: string): boolean =>
  /^\d+$/.test(raw) &&
  parseInt(raw, 10) > 0 &&
  parseInt(raw, 10) <= MAX_RETENTION_DAYS;

// A "reduction" shortens the retention window, making more chats eligible for
// permanent deletion — so it warrants a confirmation. null = Forever (∞).
const isRetentionReduction = (
  current: number | null,
  next: number | null
): boolean => {
  if (next === null) return false; // Forever is never a reduction
  if (current === null) return true; // Forever → finite shortens retention
  return next < current;
};

interface RetentionFieldProps {
  value: number | null;
  disabled?: boolean;
  onSave: (value: number | null) => void;
}

// Chat-retention control: a preset dropdown where "Custom Retention" converts
// the dropdown in place into a numeric "days" input (with revert + reopen
// affordances). The persisted shape (number | null) is unchanged, so any
// existing value — preset or not — round-trips correctly.
export default function RetentionField({
  value,
  disabled = false,
  onSave,
}: RetentionFieldProps) {
  const t = useTranslations("admin.security.adminControls");
  // Retention needs Enterprise: below it, the choices stay on show, locked
  // under an upgrade link.
  const enterpriseTier = useTierAtLeast(Tier.ENTERPRISE);
  const lockForEnterprise = useTierLockedOptions(Tier.ENTERPRISE);
  const tInputSelect = useTranslations("common.inputSelect");
  const retentionPresets = useMemo(
    () => [
      { days: 7, label: t("retention.presets.days7") },
      { days: 30, label: t("retention.presets.days30") },
      { days: 60, label: t("retention.presets.days60") },
      { days: 90, label: t("retention.presets.days90") },
      { days: 365, label: t("retention.presets.year1") },
    ],
    [t]
  );
  const [showCustom, setShowCustom] = useState(valueIsCustomRetention(value));
  const [customDays, setCustomDays] = useState(
    valueIsCustomRetention(value) ? String(value) : ""
  );
  // A pending reduction awaiting confirmation (always a positive number; null
  // means nothing is pending).
  const [pendingValue, setPendingValue] = useState<number | null>(null);
  // `pendingValue` stays set on close so the modal can animate out.
  const reduceModal = useCreateModal();

  const customInputRef = useRef<HTMLInputElement>(null);
  const focusCustomOnShowRef = useRef(false);
  // "More" focuses and clicks the select's trigger once the select is back
  // on screen: the Opal select has no controlled-open prop, and a button
  // trigger opens on click, not on focus.
  const selectWrapperRef = useRef<HTMLDivElement>(null);
  const reopenPresetsRef = useRef(false);
  // True while the presets are open in place of a stored custom value. The
  // select gives no close signal, so while it is set, a pointer down outside
  // the field and its list, or Escape, returns to the custom input.
  const [presetsReopened, setPresetsReopened] = useState(false);
  // Set when a preset is chosen from the dropdown, so leaving the dropdown
  // doesn't bounce a still-custom value back into the input (see onBlur).
  const pickedPresetRef = useRef(false);

  const syncToValue = (v: number | null) => {
    setShowCustom(valueIsCustomRetention(v));
    setCustomDays(valueIsCustomRetention(v) ? String(v) : "");
  };

  // Re-sync when the stored value changes externally (e.g. another admin),
  // but only when our local state matches the last value we persisted.
  const lastSavedRef = useRef(value);
  useEffect(() => {
    if (value === lastSavedRef.current) return;
    lastSavedRef.current = value;
    syncToValue(value);
  }, [value]);

  // Focus the custom input only when the user explicitly picks "Custom
  // Retention" (never on initial mount for an already-custom value).
  // oxlint-disable-next-line anti-slop/no-unreasoned-state-sync -- moves DOM focus to the custom input when the user picks Custom Retention
  useEffect(() => {
    if (showCustom && focusCustomOnShowRef.current) {
      customInputRef.current?.focus();
      focusCustomOnShowRef.current = false;
    }
  }, [showCustom]);

  // oxlint-disable-next-line anti-slop/no-unreasoned-state-sync -- moves DOM focus to the preset select and reopens it after Custom Retention closes
  useEffect(() => {
    if (!showCustom && reopenPresetsRef.current) {
      const trigger = selectWrapperRef.current?.querySelector("input");
      trigger?.focus();
      trigger?.click();
      reopenPresetsRef.current = false;
    }
  }, [showCustom]);

  // oxlint-disable-next-line anti-slop/no-unreasoned-state-sync -- document pointerdown and keydown listeners that close the reopened presets
  useEffect(() => {
    if (!presetsReopened) return;
    const revert = () => {
      setPresetsReopened(false);
      if (valueIsCustomRetention(value)) setShowCustom(true);
    };
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      if (selectWrapperRef.current?.contains(target)) return;
      // A pick in the portalled list lands in handleSelectChange instead.
      if (target.closest('[role="listbox"]')) return;
      revert();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") revert();
    };
    document.addEventListener("pointerdown", onPointerDown, true);
    document.addEventListener("keydown", onKeyDown, true);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown, true);
      document.removeEventListener("keydown", onKeyDown, true);
    };
  }, [presetsReopened, value]);

  // Only read while in select mode. A stored custom value (transiently visible
  // here after "More") maps to no option, so the select is left empty and the
  // trigger shows the placeholder until the user picks.
  // Below Enterprise a stored custom value cannot change, so the locked list
  // shows it as "Custom Retention" rather than the editable input.
  const selectValue =
    value === null
      ? FOREVER_RETENTION_VALUE
      : valueIsCustomRetention(value)
        ? enterpriseTier
          ? ""
          : CUSTOM_RETENTION_VALUE
        : String(value);

  const persist = (next: number | null) => {
    lastSavedRef.current = next;
    onSave(next);
  };

  // Route every save through here so reductions (preset or custom) are
  // confirmed before touching the persisted value.
  const requestPersist = (next: number | null) => {
    if (next === value) return;
    if (isRetentionReduction(value, next)) {
      setPendingValue(next);
      reduceModal.toggle(true);
      return;
    }
    persist(next);
  };

  const handleSelectChange = (next: string) => {
    setPresetsReopened(false);
    // Re-picking the selected preset unselects it; the field keeps its value.
    if (next === "") return;
    if (next === CUSTOM_RETENTION_VALUE) {
      focusCustomOnShowRef.current = true;
      setShowCustom(true);
      return;
    }
    pickedPresetRef.current = true;
    setShowCustom(false);
    requestPersist(
      next === FOREVER_RETENTION_VALUE ? null : parseInt(next, 10)
    );
  };

  // Leaving the reopened dropdown without picking a preset returns to the
  // custom input (the stored value is still custom).
  const handleSelectBlur = () => {
    if (!pickedPresetRef.current && valueIsCustomRetention(value)) {
      setShowCustom(true);
    }
    setPresetsReopened(false);
    pickedPresetRef.current = false;
  };

  const handleCustomBlur = () => {
    // Empty input reverts the field to Forever.
    if (customDays.trim() === "") {
      setShowCustom(false);
      requestPersist(null);
      return;
    }
    // Invalid input reverts to the last persisted selection.
    if (!isValidCustomRetention(customDays)) {
      syncToValue(value);
      return;
    }

    const parsed = parseInt(customDays, 10);
    const normalized = String(parsed);
    if (normalized !== customDays) setCustomDays(normalized);
    requestPersist(parsed);
  };

  // Restore Default → back to Forever.
  const handleRestoreDefault = () => {
    setShowCustom(false);
    requestPersist(null);
  };

  // More → leave custom mode and reopen the preset dropdown.
  const handleReopenPresets = () => {
    reopenPresetsRef.current = true;
    setPresetsReopened(true);
    setShowCustom(false);
  };

  const handleConfirmReduction = () => {
    if (pendingValue !== null) persist(pendingValue);
    reduceModal.toggle(false);
  };

  const handleCancelReduction = () => {
    // Discard the pending change and restore the UI to the persisted value.
    reduceModal.toggle(false);
    syncToValue(value);
  };

  const customInvalid =
    customDays !== "" && !isValidCustomRetention(customDays);

  const presetOptions: SelectOption[] = retentionPresets.map((preset) => ({
    value: String(preset.days),
    title: preset.label,
  }));
  const foreverOption: SelectOption = {
    value: FOREVER_RETENTION_VALUE,
    title: t("retention.forever.label"),
  };
  const customOption: SelectOption = {
    value: CUSTOM_RETENTION_VALUE,
    title: t("retention.custom.label"),
  };

  const iconButtonProps = {
    prominence: "tertiary",
    size: "xs",
    type: "button",
    disabled,
  } as const;

  return (
    <Section gap={2} alignItems="stretch" height="fit">
      {enterpriseTier && showCustom ? (
        <Section gap={1} alignItems="stretch" height="fit">
          <InputTypeIn
            ref={customInputRef}
            inputMode="numeric"
            pattern="[0-9]*"
            placeholder={t("retention.custom.placeholder")}
            value={customDays}
            onChange={(e) => setCustomDays(e.target.value)}
            onBlur={handleCustomBlur}
            variant={
              disabled ? "disabled" : customInvalid ? "error" : undefined
            }
            rightChildren={
              <Section flexDirection="row" gap={0.5} width="fit" height="fit">
                <Button
                  icon={SvgRevert}
                  tooltip={t("retention.custom.restoreTooltip")}
                  onClick={handleRestoreDefault}
                  {...iconButtonProps}
                />
                <Button
                  icon={SvgChevronDown}
                  tooltip={t("retention.custom.moreTooltip")}
                  onClick={handleReopenPresets}
                  {...iconButtonProps}
                />
              </Section>
            }
          />
          {customInvalid && (
            <Text font="secondary-body" color="text-03">
              {t("retention.custom.invalidError", {
                // String, not number, so ICU does not add digit grouping.
                max: String(MAX_RETENTION_DAYS),
              })}
            </Text>
          )}
        </Section>
      ) : (
        <div ref={selectWrapperRef} className="w-full">
          <InputSingleSelect
            value={selectValue}
            onValueChange={handleSelectChange}
            onBlur={handleSelectBlur}
            disabled={disabled}
            placeholder={tInputSelect("placeholder.fallback")}
            options={
              enterpriseTier
                ? [foreverOption, ...presetOptions, { options: [customOption] }]
                : // Below Enterprise every choice sits locked under an
                  // upgrade link, the stored value selected.
                  lockForEnterprise([
                    foreverOption,
                    ...presetOptions,
                    customOption,
                  ])
            }
          />
        </div>
      )}

      <reduceModal.Provider>
        {pendingValue !== null && (
          <GenericConfirmModal
            title={t("retention.reduceModal.title")}
            message={t("retention.reduceModal.message", { days: pendingValue })}
            confirmText={t("retention.reduceModal.confirmLabel")}
            onClose={handleCancelReduction}
            onConfirm={handleConfirmReduction}
          />
        )}
      </reduceModal.Provider>
    </Section>
  );
}
