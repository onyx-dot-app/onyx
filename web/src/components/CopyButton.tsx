import { useState } from "react";
import { HoverableIcon } from "./Hoverable";
import { CheckmarkIcon, CopyMessageIcon } from "./icons/icons";

export function CopyButton({
  content,
  copyAllFn,
  onClick,
}: {
  content?: string;
  copyAllFn?: () => void;
  onClick?: () => void;
}) {
  const [copyClicked, setCopyClicked] = useState(false);

  const copyToClipboard = async () => {
    try {
      // If copyAllFn is provided, use it instead of the default behavior
      if (copyAllFn) {
        await copyAllFn();
        return;
      }

      // Fall back to original behavior if no copyAllFn is provided
      if (!content) return;

      const clipboardItem = new ClipboardItem({
        "text/html": new Blob([content], { type: "text/html" }),
        "text/plain": new Blob([content], { type: "text/plain" }),
      });
      await navigator.clipboard.write([clipboardItem]);
    } catch (err) {
      // Fallback to basic text copy if HTML copy fails
      if (content) {
        await navigator.clipboard.writeText(content);
      }
    }
  };

  return (
    <HoverableIcon
      icon={copyClicked ? <CheckmarkIcon /> : <CopyMessageIcon />}
      onClick={() => {
        copyToClipboard();
        onClick && onClick();

        setCopyClicked(true);
        setTimeout(() => setCopyClicked(false), 3000);
      }}
    />
  );
}
