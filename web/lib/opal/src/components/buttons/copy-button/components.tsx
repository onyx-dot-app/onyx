"use client";

import { useEffect, useRef, useState } from "react";
import copy from "copy-to-clipboard";
import {
  Button,
  type ButtonProps,
} from "@opal/components/buttons/button/components";
import { SvgAlertTriangle, SvgCheck, SvgCopy } from "@opal/icons";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type CopyState = "idle" | "copied" | "error";

/** Omit that distributes over unions, preserving discriminated-union branches. */
type DistributiveOmit<T, K extends PropertyKey> = T extends unknown
  ? Omit<T, K>
  : never;

export type CopyButtonProps = DistributiveOmit<
  ButtonProps,
  "icon" | "onClick" | "rightIcon" | "children"
> & {
  /** Returns the text to copy to clipboard. */
  getCopyText: () => string;
  /** Returns HTML content for rich copy (falls back to plain text). */
  getHtmlContent?: () => string;
  /** Optional label. When provided, renders a text button. When omitted, renders icon-only. */
  children?: string;
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * Button that copies text to the clipboard on click.
 *
 * The icon is always `SvgCopy` (idle), `SvgCheck` (copied), or
 * `SvgAlertTriangle` (error) — callers cannot override it.
 *
 * When `children` is provided, the button renders with a text label.
 * When omitted, it renders as an icon-only button.
 */
export function CopyButton({
  getCopyText,
  getHtmlContent,
  tooltip,
  children,
  prominence = "tertiary",
  ...buttonProps
}: CopyButtonProps) {
  const [copyState, setCopyState] = useState<CopyState>("idle");
  const copyTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  async function handleCopy() {
    const text = getCopyText();

    if (copyTimeoutRef.current) {
      clearTimeout(copyTimeoutRef.current);
    }

    try {
      if (navigator.clipboard && getHtmlContent) {
        const htmlContent = getHtmlContent();
        const clipboardItem = new ClipboardItem({
          "text/html": new Blob([htmlContent], { type: "text/html" }),
          "text/plain": new Blob([text], { type: "text/plain" }),
        });
        await navigator.clipboard.write([clipboardItem]);
      } else if (navigator.clipboard) {
        await navigator.clipboard.writeText(text);
      } else if (!copy(text)) {
        throw new Error("copy-to-clipboard returned false");
      }
      setCopyState("copied");
    } catch (err) {
      console.error("Failed to copy:", err);
      setCopyState("error");
    }

    copyTimeoutRef.current = setTimeout(() => {
      setCopyState("idle");
    }, 3000);
  }

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
      default:
        return SvgCopy;
    }
  }

  function getTooltip() {
    return tooltip ?? "Copy";
  }

  const resolvedProps = {
    prominence,
    ...buttonProps,
    children,
    icon: getIcon(),
    onClick: handleCopy,
    tooltip: getTooltip(),
  } as ButtonProps;

  return <Button {...resolvedProps} />;
}
