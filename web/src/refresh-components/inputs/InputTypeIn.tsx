"use client";

import React, { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";
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

interface InputTypeInProps extends React.InputHTMLAttributes<HTMLInputElement> {
  // Input states:
  active?: boolean;
  internal?: boolean;
  disabled?: boolean;

  // Stylings:
  leftSearchIcon?: boolean;

  placeholder: string;
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
    ...props
  }: InputTypeInProps,
  ref: React.ForwardedRef<HTMLInputElement>
) {
  const { ref: boundingBoxRef, inside: hovered } = useBoundingBox();
  const [localActive, setLocalActive] = useState(active);
  const localRef = useRef<HTMLInputElement>(null);

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
        "flex flex-row items-center justify-between w-full h-fit p-spacing-interline-mini rounded-08 bg-background-neutral-00 relative",
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
        <div className="pr-spacing-interline">
          <SvgSearch className="w-[1rem] h-[1rem] stroke-text-02" />
        </div>
      )}

      <input
        ref={inputRef}
        type="text"
        placeholder={placeholder}
        disabled={disabled}
        value={value}
        onChange={onChange}
        onFocus={() => setLocalActive(true)}
        onBlur={() => setLocalActive(false)}
        className={cn(
          "w-full h-[1.5rem] bg-transparent p-spacing-inline-mini focus:outline-none",
          inputClasses(localActive)[state]
        )}
        {...props}
      />
      {value && (
        <IconButton
          icon={SvgX}
          disabled={disabled}
          onClick={handleClear}
          internal
        />
      )}
    </div>
  );
}

const InputTypeIn = React.forwardRef(InputTypeInInner);
InputTypeIn.displayName = "InputTypeIn";

export default InputTypeIn;
