"use client";

import React, { useCallback, useRef } from "react";
import { cn, noProp } from "@/lib/utils";
import SvgX from "@/icons/x";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgSearch from "@/icons/search";

const divClasses = {
  main: [
    "border",
    "hover:border-border-02",
    "active:!border-border-05",
    "focus-within-nonactive:border-border-05 focus-within-nonactive:focus-shadow",
  ],
  internal: ["border", "border-status-error-05"],
  error: [],
  disabled: [
    "bg-background-neutral-03",
    "border",
    "border-border-01",
    "cursor-not-allowed",
  ],
} as const;

const inputClasses = {
  main: [
    "text-text-04 placeholder:!font-secondary-body placeholder:text-text-02",
  ],
  internal: [],
  error: [],
  disabled: ["text-text-02"],
} as const;

export interface InputTypeInProps
  extends React.InputHTMLAttributes<HTMLInputElement> {
  // Input states:
  internal?: boolean;
  error?: boolean;
  disabled?: boolean;

  // Stylings:
  leftSearchIcon?: boolean;

  // Right section of the input, e.g. password toggle icon
  rightSection?: React.ReactNode;

  // Controls whether the clear (X) button is shown when there is a value
  showClearButton?: boolean;

  // Optional callback invoked when the clear icon is clicked for Formik compatibility
  onClear?: () => void;
}

function InputTypeInInner(
  {
    internal,
    error,
    disabled,

    leftSearchIcon,
    rightSection,
    showClearButton = true,
    onClear,

    className,
    value,
    onChange,
    ...props
  }: InputTypeInProps,
  ref: React.ForwardedRef<HTMLInputElement>
) {
  const localInputRef = useRef<HTMLInputElement | null>(null);
  const setInputRef = useCallback(
    (node: HTMLInputElement | null) => {
      localInputRef.current = node;
      if (typeof ref === "function") {
        ref(node);
      } else if (ref) {
        (ref as React.MutableRefObject<HTMLInputElement | null>).current = node;
      }
    },
    [ref]
  );

  const variant = internal ? "internal" : disabled ? "disabled" : "main";

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
      className={cn(
        "flex flex-row items-center justify-between w-full h-fit p-1.5 rounded-08 bg-background-neutral-00 relative",
        divClasses[variant],
        className
      )}
      onClick={() => {
        localInputRef.current?.focus();
      }}
    >
      {leftSearchIcon && (
        <div className="pr-2">
          <div className="pl-1">
            <SvgSearch className="w-[1rem] h-[1rem] stroke-text-02" />
          </div>
        </div>
      )}

      <input
        ref={setInputRef}
        type="text"
        disabled={disabled}
        value={value}
        onChange={onChange}
        className={cn(
          "w-full h-[1.5rem] bg-transparent p-0.5 focus:outline-none",
          inputClasses[variant]
        )}
        {...props}
      />
      {showClearButton && value && (
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
