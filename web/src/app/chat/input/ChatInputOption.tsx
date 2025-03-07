import React, { useState, useRef, useEffect } from "react";
import { ChevronDownIcon, IconProps } from "@/components/icons/icons";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

interface ChatInputOptionProps {
  name?: string;
  Icon: ({ size, className }: IconProps) => JSX.Element;
  onClick?: () => void;
  size?: number;
  tooltipContent?: React.ReactNode;
  flexPriority?: "shrink" | "stiff" | "second";
  toggle?: boolean;
  minimize?: boolean;
}

export const ChatInputOption: React.FC<ChatInputOptionProps> = ({
  name,
  Icon,
  // icon: Icon,
  size = 16,
  flexPriority,
  tooltipContent,
  toggle,
  onClick,
  minimize,
}) => {
  const componentRef = useRef<HTMLButtonElement>(null);

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            ref={componentRef}
            className={`
            relative 
            cursor-pointer 
            flex 
            items-center 
            space-x-1
            group
            rounded
            text-input-text
            hover:bg-background-chat-hover
            hover:text-neutral-900

            dark:hover:text-neutral-50
            py-1.5
            px-2
            ${
              flexPriority === "shrink" &&
              "flex-shrink-100 flex-grow-0 flex-basis-auto min-w-[30px] whitespace-nowrap overflow-hidden"
            }
            ${
              flexPriority === "second" &&
              "flex-shrink flex-basis-0 min-w-[30px] whitespace-nowrap overflow-hidden"
            }
            ${
              flexPriority === "stiff" &&
              "flex-none whitespace-nowrap overflow-hidden"
            }
          `}
            onClick={onClick}
          >
            <Icon size={size} className="h-4 w-4 my-auto  flex-none" />
            <div className={`flex items-center ${minimize && "mobile:hidden"}`}>
              {name && (
                <span className="text-sm  break-all line-clamp-1">{name}</span>
              )}
              {toggle && (
                <ChevronDownIcon className="flex-none ml-1" size={size - 4} />
              )}
            </div>
          </button>
        </TooltipTrigger>
        <TooltipContent>{tooltipContent}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
};
