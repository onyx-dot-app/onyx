"use client";

import { Persona } from "@/app/admin/assistants/interfaces";
import { AssistantIcon } from "@/components/assistants/AssistantIcon";
import { Tooltip } from "@/components/tooltip/Tooltip";
import { ForwardedRef, forwardRef, useState } from "react";
import { FiX } from "react-icons/fi";

interface DocumentSidebarProps {
  alternativeAssistant: Persona;
  unToggle: () => void;
}

export const ChatInputAssistant = forwardRef<
  HTMLDivElement,
  DocumentSidebarProps
>(({ alternativeAssistant, unToggle }, ref: ForwardedRef<HTMLDivElement>) => {
  const [isHovered, setIsHovered] = useState(false);

  return (
    <div
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      className="flex-none h-10 duration-300 h-10 items-center rounded-lg bg-background-150"
    >
      <Tooltip
        content={
          <p className="max-w-xs flex">{alternativeAssistant.description}</p>
        }
      >
        <div
          ref={ref}
          className="p-2 gap-x-1 relative rounded-t-lg items-center flex"
        >
          <AssistantIcon assistant={alternativeAssistant} border />
          <p className="ml-1 line-clamp-1 ellipsis break-all my-auto">
            {alternativeAssistant.name}
          </p>
          <div
            className="rounded-lg rounded h-fit cursor-pointer"
            onClick={unToggle}
          >
            <FiX />
          </div>
        </div>
      </Tooltip>
    </div>
  );
});

ChatInputAssistant.displayName = "TempAssistant";
export default ChatInputAssistant;
