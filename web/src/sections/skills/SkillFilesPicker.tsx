"use client";

import { useCallback, useState } from "react";
import { Button, Text } from "@opal/components";
import { SvgUploadCloud } from "@opal/icons";
import { cn } from "@opal/utils";
import { useDropzone, type FileWithPath } from "react-dropzone";
import {
  prepareSkillFilesUpload,
  type PreparedSkillFilesUpload,
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
  buttonLabel = "Add files",
  inputLabel = "Add skill files",
  prompt = "Choose files or a ZIP, or drop a folder here.",
  onChange,
  onError,
  onPreparingChange,
}: SkillFilesPickerProps) {
  const [preparing, setPreparing] = useState(false);

  const handleDrop = useCallback(
    async (files: FileWithPath[]) => {
      if (files.length === 0) return;
      setPreparing(true);
      onPreparingChange?.(true);
      try {
        onChange(await prepareSkillFilesUpload(files));
      } catch (error) {
        console.error("Failed to prepare skill files", error);
        onError(
          error instanceof Error ? error.message : "Could not read the upload."
        );
      } finally {
        setPreparing(false);
        onPreparingChange?.(false);
      }
    },
    [onChange, onError, onPreparingChange]
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
          ? "border-action-link-05 bg-action-link-01"
          : "border-border-01"
      )}
    >
      <input {...getInputProps({ "aria-label": inputLabel })} />
      <Button
        type="button"
        icon={SvgUploadCloud}
        prominence="secondary"
        disabled={disabled || preparing}
        onClick={open}
      >
        {preparing ? "Preparing..." : (busyLabel ?? buttonLabel)}
      </Button>
      <Text font="secondary-body" color="text-03">
        {value?.displayName ?? prompt}
      </Text>
    </div>
  );
}
