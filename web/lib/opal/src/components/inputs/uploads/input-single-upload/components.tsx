"use client";

import { useEffect, useRef, useState } from "react";
import UploadControl, {
  type UploadBaseProps,
} from "@opal/components/inputs/uploads/UploadControl";
import { useOpalStrings } from "@opal/strings";

/** The default: the uploaded file's text, or pasted text. */
export type InputSingleUploadTextProps = UploadBaseProps & {
  mode?: "text";
  /**
   * The value, when the caller owns it. Unset, the control keeps its own.
   * A change from outside (a reset) drops the uploaded file's name.
   */
  value?: string;
  /** Receives the uploaded file's text or the pasted text; `""` once cleared. */
  setValue: (value: string) => void;
};

/** The uploaded file itself, for a binary file such as a certificate. */
export type InputSingleUploadFileProps = UploadBaseProps & {
  mode: "file";
  /** The file, when the caller owns it. Unset, the control keeps its own. */
  value?: File | null;
  /** Receives the uploaded file, or `null` once it is cleared. */
  onFileChange: (file: File | null) => void;
};

export type InputSingleUploadProps =
  | InputSingleUploadTextProps
  | InputSingleUploadFileProps;

/**
 * An upload control for one file. Once a file is in, it shows the file's
 * name; a drop replaces it. See `UploadControl` for the picker, the drop
 * states and the keyboard.
 *
 * - `mode="text"` (default): the value is the file's text. Focused, the
 *   control also takes a paste, whose text becomes the value.
 * - `mode="file"`: the value is the `File` itself, unread, for a binary file
 *   such as a certificate.
 *
 * @example
 * ```tsx
 * <InputSingleUpload accept="application/json" setValue={setKey} />
 *
 * <InputSingleUpload mode="file" accept=".pfx" onFileChange={setCertificate} />
 * ```
 */
export default function InputSingleUpload(props: InputSingleUploadProps) {
  const strings = useOpalStrings();

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

  function takeFile(file: File) {
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

  return (
    <UploadControl
      {...props}
      label={label}
      placeholder={props.placeholder ?? strings.inputUploadPlaceholder}
      dropToAdd={strings.inputUploadDropToAdd}
      dropOverValue={strings.inputUploadDropToReplace}
      onFiles={(files) => {
        const file = files[0];
        if (file) takeFile(file);
      }}
      onClear={clear}
      onPaste={
        props.mode === "file"
          ? undefined
          : (e) => {
              const pastedText = e.clipboardData.getData("text");
              if (!pastedText) return;
              e.preventDefault();
              setSource({ kind: "paste" });
              reportText(pastedText);
            }
      }
    />
  );
}
