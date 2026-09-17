"use client";

import { useCallback, useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Text } from "@opal/components";
import { SvgUploadCloud } from "@opal/icons";
import { cn } from "@opal/utils";
import { useDropzone } from "react-dropzone";
import {
  prepareSkillBundleUpload,
  type PreparedSkillBundle,
  type SkillUploadFile,
} from "@/lib/skills/bundleUpload";

interface SkillBundlePickerProps {
  value: PreparedSkillBundle | null;
  compact?: boolean;
  disabled?: boolean;
  busyLabel?: string;
  onChange: (bundle: PreparedSkillBundle) => void;
  onError: (message: string) => void;
  onPreparingChange?: (preparing: boolean) => void;
}

export default function SkillBundlePicker({
  value,
  compact = false,
  disabled = false,
  busyLabel,
  onChange,
  onError,
  onPreparingChange,
}: SkillBundlePickerProps) {
  const t = useTranslations("skills.sections");
  const [preparing, setPreparing] = useState(false);

  const handleDrop = useCallback(
    async (files: SkillUploadFile[]) => {
      if (files.length === 0) return;
      setPreparing(true);
      onPreparingChange?.(true);
      try {
        const bundle = await prepareSkillBundleUpload(files);
        onChange(bundle);
      } catch (error) {
        console.error("Failed to prepare skill bundle", error);
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
    // Folder entries can contain any file type. The input-level accept below
    // limits only the system file picker to supported single-file uploads.
    multiple: true,
    noClick: true,
    noKeyboard: true,
    onDropAccepted: handleDrop,
  });

  return (
    <div
      {...getRootProps()}
      data-testid="skill-bundle-dropzone"
      className={cn(
        "w-full rounded-xl border border-dashed flex flex-col",
        compact
          ? "p-2 gap-1"
          : "min-h-40 items-center justify-center gap-2 p-4 text-center",
        isDragActive
          ? "bg-action-selection-01 border-action-selection-05"
          : "border-border-01"
      )}
    >
      <input
        {...getInputProps({
          accept:
            ".zip,.md,application/zip,application/x-zip-compressed,text/markdown",
        })}
      />
      <div
        className={cn(
          "flex items-center gap-2",
          !compact && "flex-col justify-center"
        )}
      >
        <Button
          type="button"
          icon={SvgUploadCloud}
          prominence="secondary"
          disabled={disabled || preparing}
          onClick={open}
        >
          {preparing
            ? t("bundlePicker.preparing.label")
            : busyLabel
              ? busyLabel
              : value
                ? t("bundlePicker.chooseDifferent.label")
                : t("bundlePicker.upload.label")}
        </Button>
        {(value || compact) && (
          <Text font="main-ui-body" color="text-03">
            {value
              ? `${value.displayName}${value.source === "folder" ? "/" : ""}`
              : t("bundlePicker.noFile.description")}
          </Text>
        )}
      </div>
    </div>
  );
}
