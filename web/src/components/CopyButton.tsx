import { useState } from "react";
import { FiCheck, FiCopy } from "react-icons/fi";
import { Hoverable, HoverableIcon } from "./Hoverable";
import { CheckmarkIcon, CopyMessageIcon } from "./icons/icons";

export function CopyButton({
  content,
  onClick,
}: {
  content?: string;
  onClick?: () => void;
}) {
  const [copyClicked, setCopyClicked] = useState(false);

  return (
    <HoverableIcon
      icon={copyClicked ? <CheckmarkIcon /> : <CopyMessageIcon />}
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
