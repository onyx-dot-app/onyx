"use client";

import { useCallback, useState } from "react";
import { useTranslations } from "next-intl";
import { FilePickerButton } from "@opal/components";
import type { IconFunctionComponent, RichStr } from "@opal/types";
import {
  prepareSkillFilesUpload,
  type PreparedSkillFilesUpload,
  type SkillUploadFile,
} from "@/lib/skills/bundleUpload";

interface SkillFilesPickerProps {
  label: string | RichStr;
  icon: IconFunctionComponent;
  disabled?: boolean;
  onChange: (upload: PreparedSkillFilesUpload) => void;
  onError: (message: string) => void;
  onPreparingChange?: (preparing: boolean) => void;
}

/** A button that picks skill files: files or a ZIP. */
export default function SkillFilesPicker({
  label,
  icon,
  disabled = false,
  onChange,
  onError,
  onPreparingChange,
}: SkillFilesPickerProps) {
  const t = useTranslations("skills.sections");
  const [preparing, setPreparing] = useState(false);

  const handleFiles = useCallback(
    async (files: SkillUploadFile[]) => {
      if (files.length === 0) return;
      setPreparing(true);
      onPreparingChange?.(true);
      try {
        onChange(await prepareSkillFilesUpload(files));
      } catch (error) {
        console.error("Failed to prepare skill files", error);
        onError(
          error instanceof Error ? error.message : t("upload.error.readFailed")
        );
      } finally {
        setPreparing(false);
        onPreparingChange?.(false);
      }
    },
    [onChange, onError, onPreparingChange, t]
  );

  return (
    <FilePickerButton
      icon={icon}
      prominence="tertiary"
      inputLabel={t("filesPicker.input.ariaLabel")}
      disabled={disabled || preparing}
      onFiles={(files) => void handleFiles(files)}
    >
      {preparing ? t("filesPicker.preparing.label") : label}
    </FilePickerButton>
  );
}
