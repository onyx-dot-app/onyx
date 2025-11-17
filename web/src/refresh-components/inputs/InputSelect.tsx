"use client";

import React from "react";
import * as SelectPrimitive from "@radix-ui/react-select";
import { cn, noProp } from "@/lib/utils";
import SvgChevronDownSmall from "@/icons/chevron-down-small";
import LineItem, { LineItemProps } from "@/refresh-components/buttons/LineItem";
import Text from "@/refresh-components/texts/Text";

const triggerClasses = {
  main: [
    "bg-background-neutral-00",
    "border",
    "hover:border-border-02",
    "data-[state=open]:border-border-05",
  ],
  error: ["border", "border-status-error-05", "bg-background-neutral-00"],
  disabled: [
    "bg-background-neutral-03",
    "border-border-01",
    "cursor-not-allowed",
  ],
} as const;

const textClasses = {
  main: ["text-text-04"],
  error: ["text-text-04"],
  disabled: ["text-text-01"],
} as const;

const iconClasses = {
  main: ["stroke-text-03"],
  error: ["stroke-text-03"],
  disabled: ["stroke-text-01"],
} as const;

interface SelectedLineItemProps {
  variant: keyof typeof textClasses;
  props?: InputSelectLineItemProps;
  placeholder?: React.ReactNode;
}

function SelectedLineItem({
  variant,
  props,
  placeholder,
}: SelectedLineItemProps) {
  if (!props) {
    if (!placeholder) return <Text text03>Select an option</Text>;
    return typeof placeholder === "string" ? (
      <Text text03>{placeholder}</Text>
    ) : (
      placeholder
    );
  }

  return (
    <div className="flex flex-row items-center gap-2 flex-1">
      {props.icon && (
        <props.icon className={cn("h-4 w-4", iconClasses[variant])} />
      )}
      <Text className={cn(textClasses[variant])}>{props.children}</Text>
    </div>
  );
}

export interface InputSelectLineItemProps
  extends Omit<LineItemProps, "heavyForced"> {
  value: string;
  selected?: boolean;
}

export function InputSelectLineItem({
  value,
  children,
  description,
  onClick,
  selected,
  ...props
}: InputSelectLineItemProps) {
  return (
    <SelectPrimitive.Item
      value={value}
      className="outline-none focus:outline-none"
      onSelect={(event) => {
        // allow consumers to hook into clicks without breaking radix behaviour
        onClick?.(event as unknown as React.MouseEvent<HTMLButtonElement>);
      }}
    >
      <LineItem
        {...props}
        heavyForced={selected}
        description={description}
        onClick={noProp((event) => event.preventDefault())}
        className={cn("w-full", props.className)}
      >
        {children}
      </LineItem>
    </SelectPrimitive.Item>
  );
}

export interface InputSelectProps {
  disabled?: boolean;
  error?: boolean;

  value?: string;
  onValueChange?: (value: string) => void;
  defaultValue?: string;
  placeholder?: React.ReactNode;
  className?: string;
  rightSection?: React.ReactNode;
  children?: React.ReactNode;
}

export default function InputSelect({
  disabled,
  error,

  value,
  onValueChange,
  defaultValue,
  placeholder,
  className,
  rightSection,
  children,
}: InputSelectProps) {
  const variant = disabled ? "disabled" : error ? "error" : "main";

  const isControlled = value !== undefined;
  const [internalValue, setInternalValue] = React.useState<string | undefined>(
    defaultValue
  );

  const currentValue = isControlled ? value : internalValue;

  React.useEffect(() => {
    if (!isControlled) {
      setInternalValue(defaultValue);
    }
  }, [defaultValue, isControlled]);

  const handleValueChange = React.useCallback(
    (nextValue: string) => {
      if (!isControlled) {
        setInternalValue(nextValue);
      }
      onValueChange?.(nextValue);
    },
    [isControlled, onValueChange]
  );

  const selectedChild = React.Children.toArray(children).find((child) => {
    if (React.isValidElement<InputSelectLineItemProps>(child)) {
      return child.props.value === currentValue;
    }
    return false;
  }) as React.ReactElement<InputSelectLineItemProps> | undefined;

  const renderedChildren = React.useMemo(
    () =>
      React.Children.map(children, (child) => {
        if (!React.isValidElement<InputSelectLineItemProps>(child)) {
          return child;
        }
        return React.cloneElement(child, {
          selected: child.props.value === currentValue,
        });
      }),
    [children, currentValue]
  );

  return (
    <SelectPrimitive.Root
      value={currentValue}
      defaultValue={defaultValue}
      onValueChange={handleValueChange}
      disabled={disabled}
    >
      <SelectPrimitive.Trigger
        className={cn(
          "group/InputSelect flex w-full items-center justify-between p-1.5 rounded-08 border outline-none",
          triggerClasses[variant],
          className
        )}
      >
        <div className="flex flex-row items-center justify-between w-full p-0.5 gap-1">
          <SelectedLineItem
            variant={variant}
            props={selectedChild?.props}
            placeholder={placeholder}
          />

          <div className="flex flex-row items-center gap-1">
            {rightSection}

            <SelectPrimitive.Icon asChild>
              <SvgChevronDownSmall
                className={cn(
                  "h-4 w-4 transition-transform",
                  iconClasses[variant],
                  "group-data-[state=open]/InputSelect:-rotate-180"
                )}
              />
            </SelectPrimitive.Icon>
          </div>
        </div>
      </SelectPrimitive.Trigger>

      <SelectPrimitive.Portal>
        <SelectPrimitive.Content
          className={cn(
            "z-[4000] w-[var(--radix-select-trigger-width)] max-h-72 overflow-auto rounded-12 border bg-background-neutral-00 p-1 pointer-events-none",
            "data-[state=open]:animate-in data-[state=closed]:animate-out",
            "data-[state=open]:fade-in-0 data-[state=closed]:fade-out-0",
            "data-[state=open]:zoom-in-95 data-[state=closed]:zoom-out-95"
          )}
          sideOffset={4}
          position="popper"
          onMouseDown={noProp()}
        >
          <SelectPrimitive.Viewport>
            {renderedChildren}
          </SelectPrimitive.Viewport>
        </SelectPrimitive.Content>
      </SelectPrimitive.Portal>
    </SelectPrimitive.Root>
  );
}
