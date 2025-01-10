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
}) => {
  const [isDropupVisible, setDropupVisible] = useState(false);
  const [isTooltipVisible, setIsTooltipVisible] = useState(false);
  const componentRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        componentRef.current &&
        !componentRef.current.contains(event.target as Node)
      ) {
        setIsTooltipVisible(false);
        setDropupVisible(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, []);

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
            text-text-700
            !rounded-lg
            hover:bg-background-chat-hover
            hover:text-emphasis
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
            <Icon
              size={size}
              className="h-4 w-4 my-auto text-[#4a4a4a] group-hover:text-text flex-none"
            />
            <div className="flex items-center">
              {name && (
                <span className="text-sm text-[#4a4a4a] group-hover:text-text break-all line-clamp-1">
                  {name}
                </span>
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
