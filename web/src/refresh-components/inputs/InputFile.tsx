"use client";

import React, { useRef, useState } from "react";
import InputTypeIn, {
  InputTypeInProps,
} from "@/refresh-components/inputs/InputTypeIn";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgPaperclip from "@/icons/paperclip";
import { noProp } from "@/lib/utils";

export interface InputFileProps
  extends Omit<
    InputTypeInProps,
    "type" | "rightSection" | "value" | "onChange" | "readOnly" | "onClear"
  > {
  // Receives the extracted file content (text) or pasted value
  setValue: (value: string) => void;
  // Called when a value is committed via file selection or paste (not on each keystroke)
  onValueSet?: (value: string, source: "file" | "paste") => void;
  // HTML accept attribute e.g. "application/json" or ".txt,.md"
  accept?: string;
  // Maximum allowed file size in kilobytes. If exceeded, file is rejected.
  maxSizeKb?: number;
  // Optional callback when the selected file exceeds max size
  onFileSizeExceeded?: (args: { file: File; maxSizeKb: number }) => void;
}

export default function InputFile({
  setValue,
  onValueSet,
  accept,
  maxSizeKb,
  onFileSizeExceeded,
  disabled,
  placeholder,
  className,
  ...rest
}: InputFileProps) {
  const [displayValue, setDisplayValue] = useState<string>("");
  const [selectedFileName, setSelectedFileName] = useState<string | null>(null);
  const [isFileMode, setIsFileMode] = useState<boolean>(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  function openFilePicker() {
    if (disabled) return;
    fileInputRef.current?.click();
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;

    // Enforce file size limit if provided
    if (typeof maxSizeKb === "number" && maxSizeKb >= 0) {
      const maxBytes = maxSizeKb * 1024;
      if (file.size > maxBytes) {
        onFileSizeExceeded?.({ file, maxSizeKb });
        // Reset file input to allow re-selecting the same file
        e.target.value = "";
        return;
      }
    }

    const reader = new FileReader();
    reader.onload = () => {
      const textContent =
        typeof reader.result === "string" ? reader.result : "";
      setValue(textContent);
      setSelectedFileName(file.name);
      setDisplayValue(file.name);
      setIsFileMode(true);
      onValueSet?.(textContent, "file");
    };
    reader.onerror = () => {
      // Reset state on error
      setSelectedFileName(null);
      setDisplayValue("");
      setIsFileMode(false);
      setValue("");
    };
    reader.readAsText(file);
    // clear the input value to allow re-selecting the same file if needed
    e.target.value = "";
  }

  function handleClear() {
    setSelectedFileName(null);
    setDisplayValue("");
    setIsFileMode(false);
    setValue("");
  }

  function handleChangeWhenTyping(e: React.ChangeEvent<HTMLInputElement>) {
    if (isFileMode) return; // ignore typing when file-mode is active
    const next = e.target.value;
    setDisplayValue(next);
    setValue(next);
  }

  function handlePaste(e: React.ClipboardEvent<HTMLInputElement>) {
    // Switch to editable mode and use pasted text as the value
    const pastedText = e.clipboardData.getData("text");
    if (!pastedText) return;
    e.preventDefault();
    setIsFileMode(false);
    setSelectedFileName(null);
    setDisplayValue(pastedText);
    setValue(pastedText);
    onValueSet?.(pastedText, "paste");
  }

  const rightSection = (
    <IconButton
      icon={SvgPaperclip}
      disabled={disabled}
      onClick={noProp(openFilePicker)}
      type="button"
      internal
      aria-label="Attach file"
    />
  );

  return (
    <>
      <input
        ref={fileInputRef}
        type="file"
        accept={accept}
        onChange={handleFileChange}
        aria-hidden
        className="hidden"
        tabIndex={-1}
        disabled={disabled}
      />
      <InputTypeIn
        {...rest}
        className={className}
        placeholder={placeholder}
        disabled={disabled}
        value={displayValue}
        onChange={handleChangeWhenTyping}
        onPaste={handlePaste}
        onClear={handleClear}
        readOnly={isFileMode}
        rightSection={rightSection}
      />
    </>
  );
}
