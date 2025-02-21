import { useState } from "react";
import { HoverableIcon } from "./Hoverable";
import { CheckmarkIcon, CopyMessageIcon } from "./icons/icons";

export function CopyButton({
  content,
  onClick,
}: {
  content?: string | { html: string; plainText: string };
  onClick?: () => void;
}) {
  const [copyClicked, setCopyClicked] = useState(false);

  const copyToClipboard = async (
    content: string | { html: string; plainText: string }
  ) => {
    try {
      const clipboardItem = new ClipboardItem({
        "text/html": new Blob(
          [typeof content === "string" ? content : content.html],
          { type: "text/html" }
        ),
        "text/plain": new Blob(
          [typeof content === "string" ? content : content.plainText],
          { type: "text/plain" }
        ),
      });
      await navigator.clipboard.write([clipboardItem]);
    } catch (err) {
      // Fallback to basic text copy if HTML copy fails
      await navigator.clipboard.writeText(
        typeof content === "string" ? content : content.plainText
      );
    }
  };

  return (
    <HoverableIcon
      icon={copyClicked ? <CheckmarkIcon /> : <CopyMessageIcon />}
      onClick={() => {
        if (content) {
          copyToClipboard(content);
        }
        onClick && onClick();

        setCopyClicked(true);
        setTimeout(() => setCopyClicked(false), 3000);
      }}
    />
  );
}
