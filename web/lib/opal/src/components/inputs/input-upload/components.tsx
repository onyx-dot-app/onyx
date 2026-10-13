"use client";

import "@opal/components/inputs/shared.css";
import "@opal/components/inputs/input-upload/styles.css";
import React, { useEffect, useRef, useState } from "react";
import { useDropzone } from "react-dropzone";
import { Button } from "@opal/components/buttons/button/components";
import { SvgImport, SvgX } from "@opal/icons";
import { noProp } from "@opal/utils";
import { useOpalStrings } from "@opal/strings";
import useWindowFileDrag from "@opal/hooks/useWindowFileDrag";
import type { InputVariants } from "@opal/types";

interface InputUploadBaseProps {
  /** Visual state, as on the other inputs. @default "primary" */
  variant?: InputVariants;
  /** Shown while nothing is uploaded; also the control's accessible name. */
  placeholder?: string;
  /** The control's id, so a label can point at it. */
  id?: string;
  /** Submitted with the hidden file input. */
  name?: string;
  /** Called when focus leaves the control. */
  onBlur?: (event: React.FocusEvent<HTMLDivElement>) => void;
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

/** The default: the uploaded file's text, or pasted text. */
export interface InputUploadTextProps extends InputUploadBaseProps {
  mode?: "text";
  /**
   * The value, when the caller owns it. Unset, the control keeps its own.
   * A change from outside (a reset) drops the uploaded file's name.
   */
  value?: string;
  /** Receives the uploaded file's text or the pasted text; `""` once cleared. */
  setValue: (value: string) => void;
}

/** The uploaded file itself, for a binary file such as a certificate. */
export interface InputUploadFileProps extends InputUploadBaseProps {
  mode: "file";
  /** The file, when the caller owns it. Unset, the control keeps its own. */
  value?: File | null;
  /** Receives the uploaded file, or `null` once it is cleared. */
  onFileChange: (file: File | null) => void;
}

export type InputUploadProps = InputUploadTextProps | InputUploadFileProps;

/** Whether `file` matches an HTML `accept` list: extensions, MIME types or `type/*`. */
function matchesAccept(file: File, accept: string | undefined): boolean {
  if (!accept) return true;
  const name = file.name.toLowerCase();
  const type = file.type.toLowerCase();
  return accept
    .split(",")
    .map((entry) => entry.trim().toLowerCase())
    .filter(Boolean)
    .some((entry) =>
      entry.startsWith(".")
        ? name.endsWith(entry)
        : entry.endsWith("/*")
          ? type.startsWith(entry.slice(0, -1))
          : type === entry
    );
}

/**
 * An upload control in the input chrome. A click (or Enter or Space) opens
 * the file picker, and a file can be dropped on it. Nothing is typed. Once a
 * file is in, it shows the file's name, and the × at the end clears it.
 *
 * While files are dragged anywhere over the page, it shows itself as a drop
 * target, darker once the pointer is over it. Its copy says what a drop
 * does: add a file, or replace the one it holds.
 *
 * - `mode="text"` (default): the value is the file's text. Focused, the
 *   control also takes a paste, whose text becomes the value.
 * - `mode="file"`: the value is the `File` itself, unread, for a binary file
 *   such as a certificate.
 *
 * @example
 * ```tsx
 * <InputUpload accept="application/json" setValue={setKey} />
 *
 * <InputUpload mode="file" accept=".pfx" onFileChange={setCertificate} />
 * ```
 */
export default function InputUpload(props: InputUploadProps) {
  const {
    variant = "primary",
    placeholder,
    id,
    name,
    onBlur,
    accept,
    maxSizeKb,
    onFileSizeExceeded,
  } = props;
  const strings = useOpalStrings();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const isNonEditable = variant === "disabled" || variant === "readOnly";

  // Text mode: the value when the caller does not own it, and what it came
  // from: a file's name, or a paste.
  const [ownText, setOwnText] = useState<string>("");
  const [source, setSource] = useState<
    { kind: "file"; name: string } | { kind: "paste" } | null
  >(null);
  // File mode: the file, when the caller does not own it.
  const [ownFile, setOwnFile] = useState<File | null>(null);

  // The last value this control reported. A different one from outside (a
  // form reset) forgets where the old value came from.
  const reportedRef = useRef<string | undefined>(undefined);
  const outsideText = props.mode !== "file" ? props.value : undefined;
  useEffect(() => {
    if (outsideText !== undefined && outsideText !== reportedRef.current) {
      setSource(null);
    }
  }, [outsideText]);

  const currentFile: File | null =
    props.mode === "file"
      ? props.value !== undefined
        ? props.value
        : ownFile
      : null;
  const currentText: string =
    props.mode === "file" ? "" : (props.value ?? ownText);

  // What the control shows: the file's name, "Pasted text", or, for a value
  // set from outside, "File attached".
  const label: string | null =
    props.mode === "file"
      ? (currentFile?.name ?? null)
      : source?.kind === "file"
        ? source.name
        : source?.kind === "paste"
          ? strings.inputUploadPasted
          : currentText
            ? strings.inputUploadAttached
            : null;
  const hasValue: boolean = label !== null;

  function reportText(text: string) {
    if (props.mode === "file") return;
    reportedRef.current = text;
    if (props.value === undefined) setOwnText(text);
    props.setValue(text);
  }

  function reportFile(file: File | null) {
    if (props.mode !== "file") return;
    if (props.value === undefined) setOwnFile(file);
    props.onFileChange(file);
  }

  function clear() {
    setSource(null);
    if (props.mode === "file") reportFile(null);
    else reportText("");
  }

  /** Takes a picked or dropped file, unless its type or size is refused. */
  function takeFile(file: File) {
    if (!matchesAccept(file, accept)) return;
    if (typeof maxSizeKb === "number" && maxSizeKb >= 0) {
      if (file.size > maxSizeKb * 1024) {
        onFileSizeExceeded?.({ file, maxSizeKb });
        return;
      }
    }
    if (props.mode === "file") {
      reportFile(file);
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      setSource({ kind: "file", name: file.name });
      reportText(typeof reader.result === "string" ? reader.result : "");
    };
    reader.onerror = clear;
    reader.readAsText(file);
  }

  // Drag and drop only: a click opens the picker below.
  const { getRootProps, isDragActive } = useDropzone({
    onDrop: (files) => {
      const file = files[0];
      if (file) takeFile(file);
    },
    multiple: false,
    disabled: isNonEditable,
    noClick: true,
    noKeyboard: true,
  });

  // While files are dragged: anywhere over the page, or over this control.
  const filesDragged = useWindowFileDrag(!isNonEditable);
  const drag: "page" | "over" | null = isDragActive
    ? "over"
    : filesDragged
      ? "page"
      : null;
  // Over the page, a held file keeps its name; over the control, the copy
  // says the drop replaces it.
  const shownLabel: string | null =
    drag === null
      ? label
      : !hasValue
        ? strings.inputUploadDropToAdd
        : drag === "over"
          ? strings.inputUploadDropToReplace
          : label;

  function openFilePicker() {
    if (!isNonEditable) fileInputRef.current?.click();
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) takeFile(file);
    // Lets the same file be picked again.
    e.target.value = "";
  }

  function handlePaste(e: React.ClipboardEvent<HTMLDivElement>) {
    if (props.mode === "file" || isNonEditable) return;
    const pastedText = e.clipboardData.getData("text");
    if (!pastedText) return;
    e.preventDefault();
    setSource({ kind: "paste" });
    reportText(pastedText);
  }

  return (
    <div
      {...getRootProps({ className: "opal-input-upload" })}
      data-drag={drag ?? undefined}
    >
      <input
        ref={fileInputRef}
        type="file"
        name={name}
        accept={accept}
        onChange={handleFileChange}
        aria-hidden
        className="hidden"
        tabIndex={-1}
        disabled={isNonEditable}
      />
      <div className="opal-input" data-variant={variant}>
        {/* The whole field picks a file; the × beside it is its own button. */}
        <div
          id={id}
          role="button"
          tabIndex={isNonEditable ? -1 : 0}
          aria-label={shownLabel ?? placeholder ?? strings.attachFile}
          aria-disabled={isNonEditable || undefined}
          data-testid={props["data-testid"]}
          className="opal-input-upload-trigger"
          onClick={openFilePicker}
          onKeyDown={(e) => {
            if (e.key !== "Enter" && e.key !== " ") return;
            e.preventDefault();
            openFilePicker();
          }}
          onPaste={handlePaste}
          onBlur={onBlur}
        >
          <div className="opal-input-leading-icon">
            <SvgImport className="opal-input-leading-icon-svg" />
          </div>
          <span
            className="opal-input-upload-label"
            data-placeholder={shownLabel === null ? true : undefined}
          >
            {shownLabel ?? placeholder}
          </span>
        </div>
        {hasValue && !isNonEditable && drag === null && (
          <Button
            icon={SvgX}
            onClick={noProp(clear)}
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
