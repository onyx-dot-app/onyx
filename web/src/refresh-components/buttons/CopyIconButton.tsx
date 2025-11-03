"use client";

import { useRef, useState } from "react";
import IconButton, { IconButtonProps } from "./IconButton";
import SvgCopy from "@/icons/copy";
import SvgCheck from "@/icons/check";

export interface CopyIconButtonProps
  extends Omit<IconButtonProps, "icon" | "onClick"> {
  // Function that returns the text to copy to clipboard
  getCopyText: () => string;
}

export default function CopyIconButton({
  getCopyText,
  tooltip,
  ...iconButtonProps
}: CopyIconButtonProps) {
  const [copied, setCopied] = useState(false);
  const copyTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  const handleCopy = () => {
    const text = getCopyText();

    // Copy to clipboard
    navigator.clipboard.writeText(text);

    // Show "copied" state
    setCopied(true);

    // Clear existing timeout if any
    if (copyTimeoutRef.current) {
      clearTimeout(copyTimeoutRef.current);
    }

    // Reset to normal state after 3 seconds
    copyTimeoutRef.current = setTimeout(() => {
      setCopied(false);
    }, 3000);
  };

  return (
    <IconButton
      icon={copied ? SvgCheck : SvgCopy}
      onClick={handleCopy}
      tooltip={copied ? "Copied!" : tooltip || "Copy"}
      {...iconButtonProps}
    />
  );
}
