"use client";

import "@opal/components/inputs/uploads/styles.css";
import React, { useRef, useState } from "react";
import {
  TagField,
  type TagItem,
} from "@opal/components/inputs/texts/input-type-in-tag/TagField";
import useUploadTarget from "@opal/components/inputs/uploads/useUploadTarget";
import type { UploadBaseProps } from "@opal/components/inputs/uploads/UploadControl";
import { SvgImport } from "@opal/icons";
import { useOpalStrings } from "@opal/strings";

export type InputMultiUploadProps = Omit<UploadBaseProps, "placeholder"> & {
  /** Shown while no file is uploaded. Default: "Add files…". */
  placeholder?: string;
  /** The files, when the caller owns them. Unset, the control keeps its own. */
  value?: File[];
  /** Receives every file the control holds, after each add or removal. */
  onFilesChange: (files: File[]) => void;
};

/** A file's identity, so picking the same file twice keeps one. */
function fileKey(file: File): string {
  return `${file.name}:${file.size}:${file.lastModified}`;
}

/**
 * An upload control for many files: each file is a removable tag inside the
 * input chrome, as on `InputMultiSelect`. A click on the field (or Enter or
 * Space) opens the file picker, and files can be dropped on it; each pick or
 * drop adds files, skipping ones it already holds. Backspace arms the last
 * tag and Backspace or Delete removes an armed one; the clear button removes
 * them all. The drop states and copy follow `InputSingleUpload`'s.
 *
 * @example
 * ```tsx
 * <InputMultiUpload value={files} onFilesChange={setFiles} />
 * ```
 */
export default function InputMultiUpload({
  variant = "primary",
  placeholder,
  id,
  name,
  onBlur,
  accept,
  maxSizeKb,
  onFileSizeExceeded,
  value,
  onFilesChange,
  ...rest
}: InputMultiUploadProps) {
  const strings = useOpalStrings();
  const triggerRef = useRef<HTMLDivElement>(null);
  const [ownFiles, setOwnFiles] = useState<File[]>([]);
  const files: File[] = value ?? ownFiles;
  const isNonEditable = variant === "disabled" || variant === "readOnly";

  function report(next: File[]) {
    if (value === undefined) setOwnFiles(next);
    onFilesChange(next);
  }

  const { getRootProps, drag, fileInput, openFilePicker, pickerOpenRef } =
    useUploadTarget({
      multiple: true,
      disabled: isNonEditable,
      // The trigger is not a labelable element; a field label opens the
      // picker through the file input instead.
      inputId: id,
      name,
      accept,
      maxSizeKb,
      onFileSizeExceeded,
      onFiles: (added) => {
        const held = new Set(files.map(fileKey));
        report([...files, ...added.filter((file) => !held.has(fileKey(file)))]);
      },
      focusTarget: () => triggerRef.current?.focus(),
    });

  // Over the page the tags stay; over the control, or with none, the field
  // says what a drop does.
  const dropCopy: string | null =
    drag === null
      ? null
      : files.length === 0
        ? strings.inputMultiUploadDropToAdd
        : drag === "over"
          ? strings.inputMultiUploadDropToAddMore
          : null;
  const tags: TagItem[] =
    dropCopy !== null
      ? []
      : files.map((file) => ({ id: fileKey(file), label: file.name }));

  return (
    <div
      {...getRootProps({ className: "opal-input-upload" })}
      data-drag={drag ?? undefined}
      data-testid={rest["data-testid"]}
      // Focus moving to the picker is not the user leaving the field.
      onBlur={(e: React.FocusEvent<HTMLButtonElement>) => {
        if (pickerOpenRef.current) return;
        if (e.currentTarget.contains(e.relatedTarget as Node | null)) return;
        onBlur?.(e);
      }}
    >
      {fileInput}
      <TagField
        tags={tags}
        onRemoveTag={(tagId) =>
          report(files.filter((file) => fileKey(file) !== tagId))
        }
        value=""
        onChange={() => {}}
        placeholder={
          dropCopy ?? placeholder ?? strings.inputMultiUploadPlaceholder
        }
        variant={variant === "error" ? "error" : "primary"}
        disabled={isNonEditable}
        icon={SvgImport}
        onClear={
          files.length > 0 && drag === null ? () => report([]) : undefined
        }
        readOnly
        triggerRef={triggerRef}
        onInputClick={openFilePicker}
        // Enter and Space open the picker, as on a button.
        onInputKeyDown={(e) => {
          if (e.key !== "Enter" && e.key !== " ") return;
          e.preventDefault();
          openFilePicker();
        }}
        inputAriaProps={{ role: "button" }}
      />
    </div>
  );
}
