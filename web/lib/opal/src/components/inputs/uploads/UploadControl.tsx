"use client";

import "@opal/components/inputs/shared.css";
import "@opal/components/inputs/uploads/styles.css";
import React, { useRef } from "react";
import { Button } from "@opal/components/buttons/button/components";
import { Text } from "@opal/components/text/components";
import { SvgImport, SvgX } from "@opal/icons";
import { noProp } from "@opal/utils";
import { useOpalStrings } from "@opal/strings";
import useUploadTarget from "@opal/components/inputs/uploads/useUploadTarget";
import type { InputVariants, RichStr } from "@opal/types";

/** The props every upload input takes, whatever it holds. */
export interface UploadBaseProps {
  /** Visual state, as on the other inputs. @default "primary" */
  variant?: InputVariants;
  /** Shown while nothing is uploaded. Accepts `markdown()`. */
  placeholder?: string | RichStr;
  /** The control's id, so a `<label htmlFor>` names it and opens it. */
  id?: string;
  /** Submitted with the hidden file input. */
  name?: string;
  /** Called when focus leaves the control (not when the picker takes it). */
  onBlur?: (event: React.FocusEvent<HTMLElement>) => void;
  "data-testid"?: string;
  /**
   * The file picker's filter, as the HTML `accept` attribute
   * (`"application/json,.json"`). A dropped file must match it too.
   */
  accept?: string;
  /** Rejects a file larger than this many kilobytes. */
  maxSizeKb?: number;
  /** Called when a file is rejected for its size. */
  onFileSizeExceeded?: (args: { file: File; maxSizeKb: number }) => void;
}

type UploadControlProps = UploadBaseProps & {
  /** What the control shows while it holds a value; `null` while empty. */
  label: string | null;
  /** Shown while empty, the caller's or the input's own default. */
  placeholder: string | RichStr;
  /** The copy while files are dragged and the control is empty. */
  dropToAdd: string;
  /** The copy while files are dragged over the control and it holds a value. */
  dropOverValue: string;
  /** Receives the picked or dropped files that pass `accept` and the size limit. */
  onFiles: (files: File[]) => void;
  /** Clears the value: the ×, or Delete or Backspace on the control. */
  onClear: () => void;
  /** A paste on the focused control, for an input that takes text. */
  onPaste?: (event: React.ClipboardEvent<HTMLButtonElement>) => void;
};

/**
 * `InputSingleUpload`'s control: the input chrome with no caret, showing one
 * value's label. A click (or Enter or Space) opens the file picker, and a
 * file can be dropped on it (see `useUploadTarget`). With a value, the × at
 * the end, or Delete or Backspace, clears it.
 */
export default function UploadControl({
  variant = "primary",
  id,
  name,
  onBlur,
  accept,
  maxSizeKb,
  onFileSizeExceeded,
  label,
  placeholder,
  dropToAdd,
  dropOverValue,
  onFiles,
  onClear,
  onPaste,
  ...rest
}: UploadControlProps) {
  const strings = useOpalStrings();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const isNonEditable = variant === "disabled" || variant === "readOnly";
  const hasValue: boolean = label !== null;
  const { getRootProps, drag, fileInput, openFilePicker, pickerOpenRef } =
    useUploadTarget({
      multiple: false,
      disabled: isNonEditable,
      name,
      accept,
      maxSizeKb,
      onFileSizeExceeded,
      onFiles,
      focusTarget: () => triggerRef.current?.focus(),
    });

  // Over the page, a held value keeps its label; over the control, the copy
  // says what a drop does to it.
  const shownLabel: string | null =
    drag === null
      ? label
      : !hasValue
        ? dropToAdd
        : drag === "over"
          ? dropOverValue
          : label;

  return (
    <div
      {...getRootProps({ className: "opal-input-upload" })}
      data-drag={drag ?? undefined}
    >
      {fileInput}
      <div className="opal-input" data-variant={variant}>
        {/* The whole field picks files, as a button a label can point at;
        the × beside it is its own button. Its name is the label, else its
        text. Enter and Space open the picker, as on any button. */}
        <button
          id={id}
          type="button"
          disabled={isNonEditable}
          data-testid={rest["data-testid"]}
          className="opal-input-upload-trigger"
          onClick={openFilePicker}
          ref={triggerRef}
          onPaste={(e) => {
            if (!isNonEditable) onPaste?.(e);
          }}
          onKeyDown={(e) => {
            // Delete or Backspace clears the value, as the × does.
            if (e.key !== "Delete" && e.key !== "Backspace") return;
            if (!hasValue) return;
            e.preventDefault();
            onClear();
          }}
          onBlur={(e) => {
            if (!pickerOpenRef.current) onBlur?.(e);
          }}
        >
          <div className="opal-input-leading-icon">
            <SvgImport className="opal-input-leading-icon-svg" />
          </div>
          <span
            className="opal-input-upload-label"
            data-placeholder={shownLabel === null ? true : undefined}
          >
            <Text
              as="p"
              font={
                drag !== null
                  ? "main-ui-action"
                  : shownLabel === null
                    ? "main-ui-muted"
                    : "main-ui-body"
              }
              color="inherit"
              maxLines={1}
            >
              {shownLabel ?? placeholder}
            </Text>
          </span>
        </button>
        {hasValue && !isNonEditable && drag === null && (
          <Button
            icon={SvgX}
            onClick={noProp(() => {
              onClear();
              // The × goes with the value, so focus returns to the control.
              triggerRef.current?.focus();
            })}
            type="button"
            prominence="internal"
            size="sm"
            aria-label={strings.clearFile}
          />
        )}
      </div>
    </div>
  );
}
