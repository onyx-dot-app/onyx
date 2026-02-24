"use client";

import { forwardRef, useEffect, useRef, useState, JSX } from "react";
import { FiCheck, FiChevronDown, FiInfo } from "react-icons/fi";
import Popover from "@/refresh-components/Popover";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
export interface Option<T> {
  name: string;
  value: T;
  description?: string;
  icon?: (props: { size?: number; className?: string }) => JSX.Element;
  // Domain-specific flag: when false, render as disabled (used by AccessTypeForm)
  disabled?: boolean;
  disabledReason?: string;
}

export type StringOrNumberOption = Option<string | number>;

export const CustomDropdown = ({
  children,
  dropdown,
  direction = "down",
}: {
  children: JSX.Element | string;
  dropdown: JSX.Element | string;
  direction?: "up" | "down";
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(event.target as Node)
      ) {
        setIsOpen(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, []);

  return (
    <div className="relative inline-block text-left w-full" ref={dropdownRef}>
      <div onClick={() => setIsOpen(!isOpen)}>{children}</div>

      {isOpen && (
        <div
          onClick={() => setIsOpen(!isOpen)}
          className={`absolute ${
            direction === "up" ? "bottom-full pb-2" : "pt-2"
          } w-full z-30 box-shadow`}
        >
          {dropdown}
        </div>
      )}
    </div>
  );
};

export function DefaultDropdownElement({
  name,
  icon,
  description,
  onSelect,
  isSelected,
  includeCheckbox = false,
  disabled = false,
  disabledReason,
}: {
  name: string | JSX.Element;
  icon?: (props: { size?: number; className?: string }) => JSX.Element;
  description?: string;
  onSelect?: () => void;
  isSelected?: boolean;
  includeCheckbox?: boolean;
  disabled?: boolean;
  disabledReason?: string;
}) {
  return (
    <div
      className={`
        flex
        mx-1
        px-2
        text-sm
        py-1.5
        my-1
        select-none
        ${disabled ? "cursor-not-allowed opacity-60" : "cursor-pointer"}
        bg-transparent
        rounded
        text-text-dark
        ${disabled ? "" : "hover:bg-accent-background-hovered"}
      `}
      onClick={disabled ? undefined : onSelect}
    >
      <div>
        <div className="flex">
          {includeCheckbox && (
            <input
              type="checkbox"
              className="mr-2"
              checked={isSelected}
              onChange={() => null}
            />
          )}
          {icon && icon({ size: 16, className: "mr-2 h-4 w-4 my-auto" })}
          {name}
          {disabled && disabledReason && (
            <SimpleTooltip tooltip={disabledReason}>
              <span className="ml-2 my-auto p-1 rounded hover:bg-background-100 text-warning transition-colors cursor-default">
                <FiInfo size={14} className="text-warning" />
              </span>
            </SimpleTooltip>
          )}
        </div>
        {description && <div className="text-xs">{description}</div>}
      </div>
      {isSelected && (
        <div className="ml-auto mr-1 my-auto">
          <FiCheck />
        </div>
      )}
    </div>
  );
}

type DefaultDropdownProps = {
  options: StringOrNumberOption[];
  selected: string | null;
  onSelect: (value: string | number | null) => void;
  includeDefault?: boolean;
  defaultValue?: string;
  side?: "top" | "right" | "bottom" | "left";
  maxHeight?: string;
};

export const DefaultDropdown = forwardRef<HTMLDivElement, DefaultDropdownProps>(
  (
    {
      options,
      selected,
      onSelect,
      includeDefault,
      defaultValue,
      side,
      maxHeight,
    },
    ref
  ) => {
    const selectedOption = options.find((option) => option.value === selected);
    const [isOpen, setIsOpen] = useState(false);

    const handleSelect = (value: any) => {
      onSelect(value);
      setIsOpen(false);
    };

    return (
      <Popover open={isOpen} onOpenChange={setIsOpen}>
        <Popover.Trigger asChild>
          <div
            className={`
              flex
              text-sm
              bg-background
              px-3
              py-1.5
              rounded-lg
              border
              border-border
              cursor-pointer
              w-full`}
          >
            <p className="line-clamp-1">
              {selectedOption?.name ||
                (includeDefault
                  ? defaultValue || "Default"
                  : "Select an option...")}
            </p>
            <FiChevronDown className="my-auto ml-auto" />
          </div>
        </Popover.Trigger>
        <Popover.Content
          align="start"
          side={side}
          sideOffset={5}
          width="trigger"
        >
          <div
            ref={ref}
            className={`
              rounded-lg
              flex
              flex-col
              bg-background
              ${maxHeight || "max-h-96"}
              overflow-y-auto
              overscroll-contain`}
          >
            {includeDefault && (
              <DefaultDropdownElement
                key={-1}
                name="Default"
                onSelect={() => handleSelect(null)}
                isSelected={selected === null}
              />
            )}
            {options.map((option, ind) => {
              const isSelected = option.value === selected;
              return (
                <DefaultDropdownElement
                  key={option.value}
                  name={option.name}
                  description={option.description}
                  onSelect={() => handleSelect(option.value)}
                  isSelected={isSelected}
                  icon={option.icon}
                  disabled={option.disabled}
                  disabledReason={option.disabledReason}
                />
              );
            })}
          </div>
        </Popover.Content>
      </Popover>
    );
  }
);
