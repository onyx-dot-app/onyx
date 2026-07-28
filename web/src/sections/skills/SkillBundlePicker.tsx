"use client";

import { useCallback, useState } from "react";
import { Button, Text } from "@opal/components";
import { SvgUploadCloud } from "@opal/icons";
import { cn } from "@opal/utils";
import { useDropzone, type FileWithPath } from "react-dropzone";
import {
  prepareSkillBundleUpload,
  type PreparedSkillBundle,
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
  const [preparing, setPreparing] = useState(false);

  const handleDrop = useCallback(
    async (files: FileWithPath[]) => {
      if (files.length === 0) return;
      setPreparing(true);
      onPreparingChange?.(true);
      try {
        const bundle = await prepareSkillBundleUpload(files);
        onChange(bundle);
      } catch (error) {
        console.error("Failed to prepare skill bundle", error);
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
          ? "bg-action-link-01 border-action-link-05"
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
            ? "Preparing upload..."
            : busyLabel
              ? busyLabel
              : value
                ? "Choose a different file"
                : "Drag and drop or click to upload"}
        </Button>
        {(value || compact) && (
          <Text font="main-ui-body" color="text-03">
            {value
              ? `${value.displayName}${value.source === "folder" ? "/" : ""}`
              : "No file selected"}
          </Text>
        )}
      </div>
    </div>
  );
}
