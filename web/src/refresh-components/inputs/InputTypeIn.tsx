"use client";

import React, { useEffect, useRef, useState } from "react";
import { cn, noProp } from "@/lib/utils";
import { useBoundingBox } from "@/hooks/useBoundingBox";
import SvgX from "@/icons/x";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgSearch from "@/icons/search";

const divClasses = (active?: boolean, hovered?: boolean) =>
  ({
    defaulted: [
      "border",
      hovered && "border-border-02",
      active && "border-border-05",
    ],
    internal: [],
    disabled: ["bg-background-neutral-03"],
  }) as const;

const inputClasses = (active?: boolean) =>
  ({
    defaulted: [
      "text-text-04 placeholder:!font-secondary-body placeholder:text-text-02",
    ],
    internal: [],
    disabled: ["text-text-02"],
  }) as const;

export interface InputTypeInProps
  extends React.InputHTMLAttributes<HTMLInputElement> {
  // Input states:
  active?: boolean;
  internal?: boolean;
  disabled?: boolean;

  // Stylings:
  leftSearchIcon?: boolean;

  // Right section of the input, e.g. password toggle icon
  rightSection?: React.ReactNode;

  placeholder: string;

  // Optional callback invoked when the clear icon is clicked for Formik compatibility
  onClear?: () => void;
}

function InputTypeInInner(
  {
    active,
    internal,
    disabled,

    leftSearchIcon,

    placeholder,
    className,
    value,
    onChange,
    onClear,
    rightSection,
    type,
    ...props
  }: InputTypeInProps,
  ref: React.ForwardedRef<HTMLInputElement>
) {
  const { ref: boundingBoxRef, inside: hovered } = useBoundingBox();
  const [localActive, setLocalActive] = useState(active);
  const localRef = useRef<HTMLInputElement>(null);

  const effectiveType = type || "text";

  // Use forwarded ref if provided, otherwise use local ref
  const inputRef = ref || localRef;

  const state = internal ? "internal" : disabled ? "disabled" : "defaulted";

  useEffect(() => {
    // if disabled, set cursor to "not-allowed"
    if (disabled && hovered) {
      document.body.style.cursor = "not-allowed";
    } else if (!disabled && hovered) {
      document.body.style.cursor = "text";
    } else {
      document.body.style.cursor = "default";
    }
  }, [hovered]);

  function handleClear() {
    if (onClear) {
      onClear();
      return;
    }

    onChange?.({
      target: { value: "" },
      currentTarget: { value: "" },
      type: "change",
      bubbles: true,
      cancelable: true,
    } as React.ChangeEvent<HTMLInputElement>);
  }

  return (
    <div
      ref={boundingBoxRef}
      className={cn(
        "flex flex-row items-center justify-between w-full h-fit p-1.5 rounded-08 bg-background-neutral-00 relative",
        divClasses(localActive, hovered)[state],
        className
      )}
      onClick={() => {
        if (
          hovered &&
          inputRef &&
          typeof inputRef === "object" &&
          inputRef.current
        ) {
          inputRef.current.focus();
        }
      }}
    >
      {leftSearchIcon && (
        <div className="pr-2">
          <SvgSearch className="w-[1rem] h-[1rem] stroke-text-02" />
        </div>
      )}

      <input
        ref={inputRef}
        type={effectiveType}
        placeholder={placeholder}
        disabled={disabled}
        value={value}
        onChange={onChange}
        className={cn(
          "w-full h-[1.5rem] bg-transparent p-0.5 focus:outline-none",
          inputClasses(localActive)[state]
        )}
        {...props}
        // Override the onFocus and onBlur props to set the local active state
        onFocus={(e) => {
          setLocalActive(true);
          props.onFocus?.(e);
        }}
        onBlur={(e) => {
          setLocalActive(false);
          props.onBlur?.(e);
        }}
      />
      {value && (
        <IconButton
          icon={SvgX}
          disabled={disabled}
          onClick={noProp(handleClear)}
          type="button"
          internal
        />
      )}
      {rightSection}
    </div>
  );
}

const InputTypeIn = React.forwardRef(InputTypeInInner);
InputTypeIn.displayName = "InputTypeIn";

export default InputTypeIn;
