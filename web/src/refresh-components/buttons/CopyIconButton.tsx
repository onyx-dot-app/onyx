"use client";

import { useEffect, useRef, useState } from "react";
import IconButton, { IconButtonProps } from "./IconButton";
import SvgCopy from "@/icons/copy";
import SvgCheck from "@/icons/check";
import SvgAlertTriangle from "@/icons/alert-triangle";

type CopyState = "idle" | "copied" | "error";

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
  const [copyState, setCopyState] = useState<CopyState>("idle");
  const copyTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  async function handleCopy() {
    const text = getCopyText();

    // Clear existing timeout if any
    if (copyTimeoutRef.current) {
      clearTimeout(copyTimeoutRef.current);
    }

    try {
      // Check if Clipboard API is available
      if (!navigator.clipboard) {
        throw new Error("Clipboard API not available");
      }

      // Copy to clipboard
      await navigator.clipboard.writeText(text);

      // Show "copied" state
      setCopyState("copied");
    } catch (err) {
      console.error("Failed to copy:", err);

      // Show "error" state
      setCopyState("error");
    }

    // Reset to normal state after 3 seconds
    copyTimeoutRef.current = setTimeout(() => {
      setCopyState("idle");
    }, 3000);
  }

  // Clean up timeout on unmount
  useEffect(() => {
    return () => {
      if (copyTimeoutRef.current) {
        clearTimeout(copyTimeoutRef.current);
      }
    };
  }, []);

  function getIcon() {
    switch (copyState) {
      case "copied":
        return SvgCheck;
      case "error":
        return SvgAlertTriangle;
      case "idle":
      default:
        return SvgCopy;
    }
  }

  function getTooltip() {
    switch (copyState) {
      case "copied":
        return "Copied!";
      case "error":
        return "Failed to copy";
      case "idle":
      default:
        return tooltip || "Copy";
    }
  }

  return (
    <IconButton
      icon={getIcon()}
      onClick={handleCopy}
      tooltip={getTooltip()}
      {...iconButtonProps}
    />
  );
}
