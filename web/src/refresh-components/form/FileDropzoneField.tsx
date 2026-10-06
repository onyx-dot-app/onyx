"use client";

import { useField } from "formik";
import { useTranslations } from "next-intl";
import { useDropzone } from "react-dropzone";
import { Button, Text } from "@opal/components";
import { SvgUploadCloud } from "@opal/icons";
import { cn } from "@opal/utils";

export interface FileDropzoneFieldProps {
  /** The Formik field name. Also the file input's id. */
  name: string;
  /** Takes many files (`File[]`) instead of one (`File | null`). */
  multiple?: boolean;
  /** Takes one .zip file. */
  isZip?: boolean;
  disabled?: boolean;
  /** Names the file input when no label points at it. */
  "aria-label"?: string;
}

/**
 * Formik-bound drop area with a file picker button. The field holds a
 * `File[]`, or one `File` (or null) when it takes a single file. Files stay
 * binary, unlike Opal's InputFile, which reads them as text.
 */
export default function FileDropzoneField({
  name,
  multiple = true,
  isZip = false,
  disabled = false,
  "aria-label": ariaLabel,
}: FileDropzoneFieldProps) {
  const t = useTranslations("common.fileDropzoneField");
  const [field, , helpers] = useField<File | File[] | null | undefined>(name);
  const single: boolean = isZip || !multiple;
  const selectedFiles: File[] = Array.isArray(field.value)
    ? field.value
    : field.value
      ? [field.value]
      : [];

  const { getRootProps, getInputProps, isDragActive, open } = useDropzone({
    disabled,
    multiple: !single,
    noClick: true,
    noKeyboard: true,
    accept: isZip ? { "application/zip": [".zip"] } : undefined,
    onDrop: (files) => {
      void helpers.setTouched(true, false);
      void helpers.setValue(single ? (files[0] ?? null) : files);
    },
  });

  const chooseLabel: string = t("chooseButton.label", {
    multiple: String(!single),
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
        {...getInputProps({ id: name, "aria-label": ariaLabel ?? chooseLabel })}
      />
      <Button
        type="button"
        icon={SvgUploadCloud}
        prominence="secondary"
        disabled={disabled}
        onClick={open}
      >
        {chooseLabel}
      </Button>
      <Text font="secondary-body" color="text-03">
        {selectedFiles.length > 0
          ? selectedFiles.map((file) => file.name).join(", ")
          : t("prompt", { multiple: String(!single) })}
      </Text>
    </div>
  );
}
