"use client";

import { useDropzone } from "react-dropzone";
import type { DistributiveOmit } from "@opal/types";
import {
  Button,
  type ButtonProps,
} from "@opal/components/buttons/button/components";

type FilePickerButtonProps = DistributiveOmit<
  ButtonProps,
  "onClick" | "href" | "download" | "type"
> & {
  /** The accessible name of the file input, which tests also select it by. */
  inputLabel: string;
  /** @default true */
  multiple?: boolean;
  /** Receives the picked or dropped files. A dropped folder's files keep
   * their folder path in `path`. */
  onFiles: (files: File[]) => void;
};

/** A Button that opens the file picker and takes files and folders dropped
 * on it. */
function FilePickerButton({
  inputLabel,
  multiple = true,
  onFiles,
  disabled,
  ...buttonProps
}: FilePickerButtonProps) {
  const { getRootProps, getInputProps, open } = useDropzone({
    multiple,
    disabled,
    noClick: true,
    noKeyboard: true,
    onDropAccepted: (files) => {
      if (files.length > 0) onFiles(files);
    },
  });

  return (
    <div {...getRootProps({ className: "inline-flex" })}>
      <input {...getInputProps({ "aria-label": inputLabel })} />
      <Button
        {...buttonProps}
        type="button"
        disabled={disabled}
        onClick={open}
      />
    </div>
  );
}

export { FilePickerButton, type FilePickerButtonProps };
