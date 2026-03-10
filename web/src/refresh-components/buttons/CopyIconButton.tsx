"use client";

import { useEffect, useRef, useState } from "react";
import { Button, ButtonProps } from "@opal/components";
import { SvgAlertTriangle, SvgCheck, SvgCopy } from "@opal/icons";

type CopyState = "idle" | "copied" | "error";

/** Omit that distributes over unions, preserving discriminated-union branches. */
type DistributiveOmit<T, K extends PropertyKey> = T extends unknown
  ? Omit<T, K>
  : never;

export type CopyIconButtonProps = DistributiveOmit<
  ButtonProps,
  "variant" | "icon" | "onClick"
> & {
  // Function that returns the text to copy to clipboard
  getCopyText: () => string;
  // Optional function to get HTML content for rich copy
  getHtmlContent?: () => string;
};

export default function CopyIconButton({
  getCopyText,
  getHtmlContent,
  tooltip,
  prominence = "tertiary",
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

      // If HTML content getter is provided, copy both HTML and plain text
      if (getHtmlContent) {
        const htmlContent = getHtmlContent();
        const clipboardItem = new ClipboardItem({
          "text/html": new Blob([htmlContent], { type: "text/html" }),
          "text/plain": new Blob([text], { type: "text/plain" }),
        });
        await navigator.clipboard.write([clipboardItem]);
      }
      // Default: plain text only
      else {
        await navigator.clipboard.writeText(text);
      }

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

  // Assertion is safe: CopyIconButton always supplies icon + onClick,
  // satisfying Button's content union. Spread may override prominence.
  const buttonProps = {
    prominence,
    ...iconButtonProps,
    icon: getIcon(),
    onClick: handleCopy,
    tooltip: getTooltip(),
  } as ButtonProps;

  return <Button {...buttonProps} />;
}
