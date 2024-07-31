import React, { useState, useRef, useEffect } from "react";
import { IconType } from "react-icons";
import { DefaultDropdownElement } from "../../../components/Dropdown";
import { Popover } from "../../../components/popover/Popover";
import { IconProps } from "@/components/icons/icons";

interface ChatInputOptionProps {
  name?: string;
  Icon: ({ size, className }: IconProps) => JSX.Element;
  onClick?: () => void;
  size?: number;
  tooltipContent?: React.ReactNode;
  options?: { name: string; value: number; onClick?: () => void }[];
  flexPriority?: "shrink" | "stiff" | "second";
}

export const ChatInputOption: React.FC<ChatInputOptionProps> = ({
  name,
  Icon,
  // icon: Icon,
  size = 16,
  options,
  flexPriority,
  tooltipContent,
  onClick,
}) => {
  const [isDropupVisible, setDropupVisible] = useState(false);
  const [isTooltipVisible, setIsTooltipVisible] = useState(false);
  const componentRef = useRef<HTMLDivElement>(null);

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
    <div
      ref={componentRef}
      className={`
        relative 
        cursor-pointer 
        flex 
        items-center 
        space-x-2 
        text-text-700
        hover:bg-hover
        hover:text-emphasis
        p-1.5
        rounded-md
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
      title={name}
      onClick={onClick}
    >
      <Icon size={size} className="flex-none" />
      {name && <span className="text-sm break-all line-clamp-1">{name}</span>}
      {isTooltipVisible && tooltipContent && (
        <div
          className="absolute z-10 p-2 text-sm text-white bg-black rounded shadow-lg"
          style={{
            top: "100%",
            left: "50%",
            transform: "translateX(-50%)",
            marginTop: "0.5rem",
            whiteSpace: "nowrap",
          }}
        >
          {tooltipContent}
        </div>
      )}
    </div>
  );
};
