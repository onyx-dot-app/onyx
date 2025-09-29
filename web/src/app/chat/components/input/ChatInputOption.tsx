import React, { useRef } from "react";
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
  const componentRef = useRef<HTMLDivElement>(null);

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <div
            ref={componentRef}
            className={`
            relative
            cursor-pointer
            flex
            items-center
            ${name ? "space-x-1" : ""}
            group
            rounded-lg
            text-input-text
            hover:text-neutral-900
            hover:bg-background-chat-hover
            dark:hover:text-neutral-50
            transition-all
            duration-300
            ease-in-out
            py-1.5
            px-2
            h-8
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
            <Icon size={size} className="h-4 w-4 my-auto flex-none" />
            <div className={`flex items-center ${minimize && "mobile:hidden"}`}>
              {name && (
                <span className="text-sm break-all line-clamp-1">{name}</span>
              )}
              {toggle && (
                <ChevronDownIcon
                  className={"flex-none " + (name ? "ml-1" : "")}
                  size={size - 4}
                />
              )}
            </div>
          </div>
        </TooltipTrigger>
        <TooltipContent>{tooltipContent}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
};
