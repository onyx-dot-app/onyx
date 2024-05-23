import { useState } from "react";
import { FiCheck, FiCopy } from "react-icons/fi";
import { Hoverable } from "./Hoverable";

export function CopyButton({
  content,
  onClick,
}: {
  content?: string;
  onClick?: () => void;
}) {
  const [copyClicked, setCopyClicked] = useState(false);

  return (
    <Hoverable
      icon={copyClicked ? FiCheck : FiCopy}
      onClick={() => {
        if (content) {
          navigator.clipboard.writeText(content.toString());
        }
        onClick && onClick();

        setCopyClicked(true);
        setTimeout(() => setCopyClicked(false), 3000);
      }}
    />
  );
}
