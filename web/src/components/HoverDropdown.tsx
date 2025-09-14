import { FC, useState, useRef, useEffect } from "react";
import { FiFolder, FiChevronRight } from "react-icons/fi";

export interface DropdownItem {
  id: string;
  label: string;
  description?: string;
  icon?: React.FC<{ size?: number; className?: string }>;
  isSelected?: boolean;
}

interface HoverDropdownProps {
  label: string | JSX.Element;
  items: DropdownItem[];
  onItemClick: (item: DropdownItem) => void;
  className?: string;
  dropdownClassName?: string;
  emptyMessage?: string;
}

export const HoverDropdown: FC<HoverDropdownProps> = ({
  label,
  items,
  onItemClick,
  className = "",
  dropdownClassName = "",
  emptyMessage = "No items to show",
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const timeoutRef = useRef<NodeJS.Timeout>();

  const handleMouseEnter = () => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }
    setIsOpen(true);
  };

  const handleMouseLeave = () => {
    timeoutRef.current = setTimeout(() => {
      setIsOpen(false);
    }, 150);
  };

  useEffect(() => {
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, []);

  return (
    <div
      className={`relative ${className}`}
      ref={dropdownRef}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      <div
        className={`
          flex
          mx-1
          px-2
          text-sm 
          py-1.5 
          my-1
          select-none 
          cursor-pointer 
          bg-transparent 
          rounded
          text-text-dark
          hover:bg-accent-background-hovered
        `}
      >
        <div className="flex w-full justify-between items-center">
          <div className="flex">
            <FiFolder size={16} className="mr-2 h-4 w-4 my-auto" />
            {label}
          </div>
          <FiChevronRight size={16} className="ml-2 h-4 w-4 my-auto" />
        </div>
      </div>

      {isOpen && (
        <div
          className={`
            absolute 
            left-full
            top-0
            ml-1
            border 
            border-border 
            rounded-lg 
            flex 
            flex-col 
            bg-background
            shadow-lg
            min-w-[200px]
            ${dropdownClassName}
          `}
        >
          {items.length > 0 ? (
            items.map((item) => (
              <div
                key={item.id}
                onClick={() => {
                  onItemClick(item);
                  setIsOpen(false);
                }}
                className={`
                flex
                mx-1
                px-2
                text-sm 
                py-1.5 
                my-1
                select-none 
                cursor-pointer 
                bg-transparent 
                rounded
                text-text-dark
                hover:bg-accent-background-hovered
              `}
              >
                <div>
                  <div className="flex">
                    <FiFolder size={16} className="mr-2 h-4 w-4 my-auto" />
                    {item.label}
                  </div>
                  {item.description && (
                    <div className="text-xs text-text-500">
                      {item.description}
                    </div>
                  )}
                </div>
              </div>
            ))
          ) : (
            <div className="text-sm px-3 py-1.5 text-text-500">
              {emptyMessage}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
