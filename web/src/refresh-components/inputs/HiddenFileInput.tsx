"use client";

import {
  forwardRef,
  useImperativeHandle,
  useRef,
  type ChangeEvent,
} from "react";

export interface HiddenFileInputHandle {
  /** Opens the native file dialog. */
  open: () => void;
}

interface HiddenFileInputProps {
  onFiles: (files: File[]) => void;
  accept?: string;
  multiple?: boolean;
}

/**
 * A visually hidden `<input type="file">` exposed via an imperative `open()`.
 * There's no design-system file input — opening the OS file dialog requires
 * the native element — so this wraps it so callers don't inline raw markup.
 */
const HiddenFileInput = forwardRef<HiddenFileInputHandle, HiddenFileInputProps>(
  ({ onFiles, accept, multiple = false }, ref) => {
    const inputRef = useRef<HTMLInputElement>(null);

    useImperativeHandle(ref, () => ({
      open: () => inputRef.current?.click(),
    }));

    return (
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        multiple={multiple}
        aria-hidden
        tabIndex={-1}
        className="hidden"
        onChange={(e: ChangeEvent<HTMLInputElement>) => {
          const files = e.target.files;
          if (files && files.length > 0) onFiles(Array.from(files));
          e.target.value = "";
        }}
      />
    );
  }
);

HiddenFileInput.displayName = "HiddenFileInput";

export default HiddenFileInput;
