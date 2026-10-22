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
  name?: string;
  /** The picker's filter, as the HTML `accept` attribute; a drop must match it too. */
  accept?: string;
  maxSizeKb?: number;
  onFileSizeExceeded?: (args: { file: File; maxSizeKb: number }) => void;
  /** Receives the picked, dropped or pasted files that pass `accept` and the size limit. */
  onFiles: (files: File[]) => void;
  /** Receives a paste without files, for an input that takes text. */
  onPasteText?: (text: string) => void;
  /** Where focus returns when the picker closes. */
  focusTarget: () => void;
}

/**
 * What the upload inputs share: the file picker, dropping and pasting
 * files, and the drag state. While files are dragged anywhere over the page, `drag` is
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
  name,
  accept,
  maxSizeKb,
  onFileSizeExceeded,
  onFiles,
  onPasteText,
  focusTarget,
}: UseUploadTargetOptions) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pickerOpenRef = useRef<boolean>(false);
  // The latest focus target, kept current after each commit.
  const focusTargetRef = useRef(focusTarget);
  useEffect(() => {
    focusTargetRef.current = focusTarget;
  });

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

  // Drag and drop only: a click focuses the control, so a copied file can
  // be pasted; a double click opens the picker. The dropzone's own paste is
  // off, see the paste listener below.
  const { getRootProps, isDragActive, rootRef } = useDropzone({
    onDrop: takeFiles,
    multiple,
    disabled,
    noClick: true,
    noKeyboard: true,
    noPaste: true,
  });

  // A paste goes to the focused control. Browsers send `paste` to the text
  // selection, not to a focused button or read-only field, so the event's
  // target can be any element; the control takes it while focus is inside.
  const pasteRef = useRef<(event: ClipboardEvent) => void>(() => {});
  pasteRef.current = (event) => {
    const root = rootRef.current;
    if (disabled || !root || !root.contains(document.activeElement)) return;
    const data = event.clipboardData;
    if (!data) return;
    const files = Array.from(data.files);
    if (files.length > 0) {
      event.preventDefault();
      takeFiles(files);
      return;
    }
    const text = data.getData("text");
    if (!text || !onPasteText) return;
    event.preventDefault();
    onPasteText(text);
  };
  useEffect(() => {
    const onPaste = (event: ClipboardEvent) => pasteRef.current(event);
    document.addEventListener("paste", onPaste);
    return () => document.removeEventListener("paste", onPaste);
  }, []);
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

  // Runs on every click of the file input, including one from a field
  // label, so each way of opening the picker is tracked.
  function markPickerOpen() {
    pickerOpenRef.current = true;
    // Where the picker sends no cancel event, focus returning to the page
    // marks it closed.
    window.addEventListener("focus", () => setTimeout(closePicker), {
      once: true,
    });
  }

  function openFilePicker() {
    if (disabled) return;
    fileInputRef.current?.click();
  }

  const fileInput = (
    <input
      ref={fileInputRef}
      type="file"
      name={name}
      accept={accept}
      multiple={multiple}
      onClick={markPickerOpen}
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

  return {
    getRootProps,
    drag,
    fileInput,
    openFilePicker,
    pickerOpenRef,
  };
}
