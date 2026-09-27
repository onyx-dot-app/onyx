"use client";

import { useCallback, useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Text } from "@opal/components";
import { SvgUploadCloud } from "@opal/icons";
import { cn } from "@opal/utils";
import { useDropzone } from "react-dropzone";
import {
  prepareSkillFilesUpload,
  type PreparedSkillFilesUpload,
  type SkillUploadFile,
} from "@/lib/skills/bundleUpload";

interface SkillFilesPickerProps {
  value?: PreparedSkillFilesUpload | null;
  disabled?: boolean;
  busyLabel?: string;
  buttonLabel?: string;
  inputLabel?: string;
  prompt?: string;
  onChange: (upload: PreparedSkillFilesUpload) => void;
  onError: (message: string) => void;
  onPreparingChange?: (preparing: boolean) => void;
}

export default function SkillFilesPicker({
  value,
  disabled = false,
  busyLabel,
  buttonLabel,
  inputLabel,
  prompt,
  onChange,
  onError,
  onPreparingChange,
}: SkillFilesPickerProps) {
  const t = useTranslations("skills.sections");
  const [preparing, setPreparing] = useState(false);

  const handleDrop = useCallback(
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

  const { getRootProps, getInputProps, isDragActive, open } = useDropzone({
    disabled: disabled || preparing,
    multiple: true,
    noClick: true,
    noKeyboard: true,
    onDropAccepted: handleDrop,
  });

  return (
    <div
      {...getRootProps()}
      className={cn(
        "flex w-full items-center gap-2 rounded-xl border border-dashed p-2",
        isDragActive
          ? "border-action-selection-05 bg-action-selection-01"
          : "border-border-01"
      )}
    >
      <input
        {...getInputProps({
          "aria-label": inputLabel ?? t("filesPicker.input.ariaLabel"),
        })}
      />
      <Button
        type="button"
        icon={SvgUploadCloud}
        prominence="secondary"
        disabled={disabled || preparing}
        onClick={open}
      >
        {preparing
          ? t("filesPicker.preparing.label")
          : (busyLabel ?? buttonLabel ?? t("filesPicker.addFiles.label"))}
      </Button>
      <Text font="secondary-body" color="text-03">
        {value?.displayName ?? prompt ?? t("filesPicker.prompt.description")}
      </Text>
    </div>
  );
}
