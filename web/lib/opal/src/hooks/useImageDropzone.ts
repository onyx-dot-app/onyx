"use client";

import { useCallback } from "react";
import { useDropzone, DropzoneOptions, FileRejection } from "react-dropzone";

const ACCEPTED_IMAGE_TYPES = {
  "image/png": [".png"],
  "image/jpeg": [".jpeg", ".jpg"],
};

export interface UseImageDropzoneOptions {
  /** Callback when a valid image file is dropped/selected */
  onImageAccepted: (file: File) => void;
  /** Callback when file is rejected (wrong type, too many files, etc.) */
  onImageRejected?: (rejections: FileRejection[]) => void;
  /** Whether dropzone is disabled */
  disabled?: boolean;
  /** Custom accepted file types - defaults to png, jpeg, jpg */
  accept?: DropzoneOptions["accept"];
}

export interface UseImageDropzoneReturn {
  /** Whether user is actively dragging files over the drop zone */
  isDragActive: boolean;
  /** Props to spread onto the drop zone container element */
  getRootProps: ReturnType<typeof useDropzone>["getRootProps"];
  /** Props to spread onto a hidden input element */
  getInputProps: ReturnType<typeof useDropzone>["getInputProps"];
  /** Programmatically open the file picker (for click-to-edit) */
  openFilePicker: () => void;
}

export function useImageDropzone({
  onImageAccepted,
  onImageRejected,
  disabled = false,
  accept = ACCEPTED_IMAGE_TYPES,
}: UseImageDropzoneOptions): UseImageDropzoneReturn {
  const onDrop = useCallback(
    (acceptedFiles: File[], rejections: FileRejection[]) => {
      if (rejections.length > 0) {
        onImageRejected?.(rejections);
        return;
      }

      const file = acceptedFiles[0];
      if (file) {
        onImageAccepted(file);
      }
    },
    [onImageAccepted, onImageRejected]
  );

  const { getRootProps, getInputProps, open, isDragActive } = useDropzone({
    onDrop,
    accept,
    multiple: false,
    disabled,
    noClick: true,
    noKeyboard: true,
  });

  return {
    isDragActive,
    getRootProps,
    getInputProps,
    openFilePicker: open,
  };
}
