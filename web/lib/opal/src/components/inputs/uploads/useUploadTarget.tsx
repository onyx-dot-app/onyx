"use client";

import { useEffect, useRef } from "react";
import { useDropzone } from "react-dropzone";
import useWindowFileDrag from "@opal/hooks/useWindowFileDrag";

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

interface UseUploadTargetOptions {
  /** Whether the picker and a drop take several files. */
  multiple: boolean;
  /** No picking or dropping. */
  disabled: boolean;
  /** An id for the hidden file input, so a `<label htmlFor>` opens it. */
  inputId?: string;
  name?: string;
  /** The picker's filter, as the HTML `accept` attribute; a drop must match it too. */
  accept?: string;
  maxSizeKb?: number;
  onFileSizeExceeded?: (args: { file: File; maxSizeKb: number }) => void;
  /** Receives the picked or dropped files that pass `accept` and the size limit. */
  onFiles: (files: File[]) => void;
  /** Where focus returns when the picker closes. */
  focusTarget: () => void;
}

/**
 * What the upload inputs share: the file picker, dropping, and the drag
 * state. While files are dragged anywhere over the page, `drag` is
 * `"page"`; over the control's root, `"over"`.
 *
 * The picker takes focus from the control. That blur is not the user leaving
 * the field, so `pickerOpenRef` lets the control skip it (a form would mark
 * the field touched and show "required" mid-pick); focus returns to
 * `focusTarget` when the picker closes.
 */
export default function useUploadTarget({
  multiple,
  disabled,
  inputId,
  name,
  accept,
  maxSizeKb,
  onFileSizeExceeded,
  onFiles,
  focusTarget,
}: UseUploadTargetOptions) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pickerOpenRef = useRef<boolean>(false);
  const focusTargetRef = useRef(focusTarget);
  focusTargetRef.current = focusTarget;

  function takeFiles(files: File[]) {
    const allowed = files.filter((file) => {
      if (!matchesAccept(file, accept)) return false;
      if (
        typeof maxSizeKb === "number" &&
        maxSizeKb >= 0 &&
        file.size > maxSizeKb * 1024
      ) {
        onFileSizeExceeded?.({ file, maxSizeKb });
        return false;
      }
      return true;
    });
    if (allowed.length > 0) onFiles(multiple ? allowed : allowed.slice(0, 1));
  }

  // Drag and drop only: a click opens the picker.
  const { getRootProps, isDragActive } = useDropzone({
    onDrop: takeFiles,
    multiple,
    disabled,
    noClick: true,
    noKeyboard: true,
  });
  const filesDragged = useWindowFileDrag(!disabled);
  const drag: "page" | "over" | null = isDragActive
    ? "over"
    : filesDragged
      ? "page"
      : null;

  function closePicker() {
    if (!pickerOpenRef.current) return;
    pickerOpenRef.current = false;
    focusTargetRef.current();
  }
  useEffect(() => {
    const input = fileInputRef.current;
    if (!input) return;
    input.addEventListener("cancel", closePicker);
    return () => input.removeEventListener("cancel", closePicker);
  }, []);

  function openFilePicker() {
    if (disabled) return;
    pickerOpenRef.current = true;
    // Where the picker sends no cancel event, focus returning to the page
    // marks it closed.
    window.addEventListener("focus", () => setTimeout(closePicker), {
      once: true,
    });
    fileInputRef.current?.click();
  }

  const fileInput = (
    <input
      ref={fileInputRef}
      id={inputId}
      type="file"
      name={name}
      accept={accept}
      multiple={multiple}
      onChange={(e) => {
        closePicker();
        takeFiles(Array.from(e.target.files ?? []));
        // Lets the same file be picked again.
        e.target.value = "";
      }}
      aria-hidden
      className="hidden"
      tabIndex={-1}
      disabled={disabled}
    />
  );

  return { getRootProps, drag, fileInput, openFilePicker, pickerOpenRef };
}
