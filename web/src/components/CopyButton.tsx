import { Hoverable } from "@/app/chat/message/Messages";
import { useState } from "react";
import { FiCheck, FiCopy } from "react-icons/fi";

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
      onClick={() => {
        if (content) {
          navigator.clipboard.writeText(content.toString());
        }
        onClick && onClick();

        setCopyClicked(true);
        setTimeout(() => setCopyClicked(false), 3000);
      }}
    >
      {copyClicked ? <FiCheck /> : <FiCopy />}
    </Hoverable>
  );
}
