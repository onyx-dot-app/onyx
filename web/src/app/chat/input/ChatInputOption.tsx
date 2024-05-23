import React, { useState } from "react";
import { IconType } from "react-icons";
import { DefaultDropdownElement } from "../../../components/Dropdown";
import { Popover } from "../../../components/popover/Popover";

interface ChatInputOptionProps {
  name: string;
  icon: IconType;
  onClick: () => void;
  size?: number;
  options?: { name: string; value: number; onClick?: () => void }[];
}

const ChatInputOption = ({
  name,
  icon: Icon,
  onClick,
  size = 16,
  options,
}: ChatInputOptionProps) => {
  const [isDropupVisible, setDropupVisible] = useState(false);

  const handleClick = () => {
    setDropupVisible(!isDropupVisible);
    // onClick();
  };

  const dropdownContent = options ? (
    <div
      className={`
        border 
        border 
        rounded-lg 
        flex 
        flex-col 
        bg-background
        overflow-y-auto 
        overscroll-contain`}
    >
      {options.map((option) => (
        <DefaultDropdownElement
          key={option.value}
          name={option.name}
          onSelect={() => {
            if (option.onClick) {
              option.onClick();
              setDropupVisible(false);
            }
          }}
          isSelected={false}
        />
      ))}
    </div>
  ) : null;

  const option = (
    <div className="relative w-fit">
      <div
        className="
          cursor-pointer 
          flex 
          items-center 
          space-x-2 
          text-subtle
          hover:bg-hover
          hover:text-emphasis
          p-1.5
          rounded-md
        "
        onClick={handleClick}
        title={name}
      >
        <Icon size={size} />
        <span className="text-sm">{name}</span>
      </div>
    </div>
  );

  if (!dropdownContent) {
    return <div onClick={onClick}>{option}</div>;
  }

  return (
    <Popover
      open={isDropupVisible}
      onOpenChange={setDropupVisible}
      content={option}
      popover={dropdownContent}
      side="top"
      align="start"
      sideOffset={5}
    />
  );
};

export default ChatInputOption;
