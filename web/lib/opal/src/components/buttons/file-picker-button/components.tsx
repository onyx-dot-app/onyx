"use client";

import { useRef } from "react";
import type { DistributiveOmit } from "@opal/types";
import {
  Button,
  type ButtonProps,
} from "@opal/components/buttons/button/components";

type FilePickerButtonProps = DistributiveOmit<
  ButtonProps,
  "onClick" | "href" | "type"
> & {
  /** The accessible name of the file input, which tests also select it by. */
  inputLabel: string;
  /** The picker's filter, as the HTML `accept` attribute. */
  accept?: string;
  /** @default true */
  multiple?: boolean;
  /** Receives the picked files. */
  onFiles: (files: File[]) => void;
};

/** A Button that opens the file picker and hands the picked files to `onFiles`. */
function FilePickerButton({
  inputLabel,
  accept,
  multiple = true,
  onFiles,
  disabled,
  ...buttonProps
}: FilePickerButtonProps) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <>
      <input
        ref={input}
        type="file"
        aria-label={inputLabel}
        accept={accept}
        multiple={multiple}
        disabled={disabled}
        tabIndex={-1}
        className="hidden"
        onChange={(event) => {
          const files = Array.from(event.target.files ?? []);
          // Lets the same file be picked again.
          event.target.value = "";
          if (files.length > 0) onFiles(files);
        }}
      />
      <Button
        {...buttonProps}
        type="button"
        disabled={disabled}
        onClick={() => input.current?.click()}
      />
    </>
  );
}

export { FilePickerButton, type FilePickerButtonProps };
