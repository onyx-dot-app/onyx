"use client";

import { useCallback, useState } from "react";
import { useTranslations } from "next-intl";
import { Section } from "@opal/layouts";
import { Button, Text } from "@opal/components";
import { SvgFolder, SvgUploadCloud } from "@opal/icons";
import { cn } from "@opal/utils";
import { useDropzone } from "react-dropzone";
import {
  prepareSkillBundleUpload,
  SkillFolderRootError,
  type PreparedSkillBundle,
  type SkillUploadFile,
} from "@/lib/skills/bundleUpload";

interface SkillBundlePickerProps {
  value: PreparedSkillBundle | null;
  compact?: boolean;
  disabled?: boolean;
  allowPlugin?: boolean;
  busyLabel?: string;
  onChange: (bundle: PreparedSkillBundle) => void;
  onBatchChange?: (files: File[]) => void;
  onError: (message: string) => void;
  onPreparingChange?: (preparing: boolean) => void;
}

export default function SkillBundlePicker({
  value,
  compact = false,
  disabled = false,
  allowPlugin = false,
  busyLabel,
  onChange,
  onBatchChange,
  onError,
  onPreparingChange,
}: SkillBundlePickerProps) {
  const t = useTranslations("skills.sections");
  const [preparing, setPreparing] = useState(false);

  const handleDrop = useCallback(
    async (files: SkillUploadFile[]) => {
      if (files.length === 0) return;
      if (
        onBatchChange &&
        files.length > 1 &&
        files.every(
          (file) =>
            file.name.toLowerCase().endsWith(".zip") &&
            (!file.path || file.path.replace(/^\.?\//, "") === file.name)
        )
      ) {
        onBatchChange(files);
        return;
      }
      setPreparing(true);
      onPreparingChange?.(true);
      try {
        const bundle = await prepareSkillBundleUpload(files, { allowPlugin });
        onChange(bundle);
      } catch (error) {
        console.error("Failed to prepare skill bundle", error);
        onError(
          error instanceof SkillFolderRootError
            ? t("upload.error.folderRoot", { upload: error.upload })
            : error instanceof Error
              ? error.message
              : t("upload.error.readFailed")
        );
      } finally {
        setPreparing(false);
        onPreparingChange?.(false);
      }
    },
    [allowPlugin, onBatchChange, onChange, onError, onPreparingChange, t]
  );

  const { getRootProps, getInputProps, isDragActive, open, inputRef } =
    useDropzone({
      disabled: disabled || preparing,
      // Folder entries can contain any file type. The input-level accept below
      // limits only the system file picker to supported single-file uploads.
      multiple: true,
      noClick: true,
      noKeyboard: true,
      onDropAccepted: handleDrop,
      onFileDialogCancel: () =>
        inputRef.current?.removeAttribute("webkitdirectory"),
    });

  function pick(folder: boolean) {
    const input = inputRef.current;
    if (!input) return;
    // One input serves both pickers: the folder picker sets webkitdirectory
    // only while it is open.
    if (folder) input.setAttribute("webkitdirectory", "");
    else input.removeAttribute("webkitdirectory");
    open();
  }

  return (
    <Section
      {...getRootProps()}
      height="auto"
      alignItems={compact ? "stretch" : "center"}
      justifyContent="center"
      gap={compact ? 1 : 2}
      padding={compact ? 2 : 4}
      data-testid="skill-bundle-dropzone"
      className={cn(
        "rounded-xl border border-dashed",
        !compact && "min-h-40 text-center",
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
      <Section height="auto" flexDirection={compact ? "row" : "column"} gap={2}>
        <Button
          type="button"
          icon={SvgUploadCloud}
          prominence="secondary"
          disabled={disabled || preparing}
          onClick={() => pick(false)}
        >
          {preparing
            ? t("bundlePicker.preparing.label")
            : busyLabel
              ? busyLabel
              : value
                ? t("bundlePicker.chooseDifferent.label")
                : t("bundlePicker.upload.label")}
        </Button>
        {allowPlugin && !preparing && !busyLabel && (
          <Button
            type="button"
            icon={SvgFolder}
            prominence="tertiary"
            disabled={disabled}
            onClick={() => pick(true)}
          >
            {t("bundlePicker.chooseFolder.label")}
          </Button>
        )}
        {(value || compact) && (
          <Text font="main-ui-body" color="text-03">
            {value
              ? `${value.displayName}${value.source === "folder" ? "/" : ""}`
              : t("bundlePicker.noFile.description")}
          </Text>
        )}
      </Section>
    </Section>
  );
}
