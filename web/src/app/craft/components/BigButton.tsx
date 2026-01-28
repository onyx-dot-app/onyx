"use client";

import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";

export interface BigButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement> {
  // Subvariants
  primary?: boolean;
  secondary?: boolean;

  // Inverted mode for dark backgrounds
  inverted?: boolean;
}

const BigButton = forwardRef<HTMLButtonElement, BigButtonProps>(
  (
    { primary, secondary, inverted, disabled, children, className, ...props },
    ref
  ) => {
    const subvariant = primary
      ? "primary"
      : secondary
        ? "secondary"
        : "primary";

    const baseStyles =
      "px-6 py-3 rounded-xl w-fit flex flex-row items-center justify-center transition-colors";

    const variantStyles = {
      primary: {
        normal:
          "bg-theme-primary-05 hover:bg-theme-primary-04 active:bg-theme-primary-06",
        inverted: "bg-white hover:bg-gray-200 active:bg-gray-300",
        disabled: "bg-background-neutral-04",
      },
      secondary: {
        normal:
          "bg-transparent border border-border-01 hover:bg-background-tint-02 active:bg-background-tint-00",
        inverted:
          "bg-transparent border border-text-inverted-05 hover:bg-background-tint-inverted-02 active:bg-background-tint-inverted-01",
        disabled: "bg-background-neutral-03 border border-border-01",
      },
    };

    const textStyles = {
      primary: {
        normal: "text-text-inverted-05",
        inverted: "text-gray-900",
        disabled: "text-text-inverted-04",
      },
      secondary: {
        normal:
          "text-text-03 group-hover:text-text-04 group-active:text-text-05",
        inverted: "text-text-inverted-05",
        disabled: "text-text-01",
      },
    };

    const getVariantStyle = () => {
      if (disabled) return variantStyles[subvariant].disabled;
      return inverted
        ? variantStyles[subvariant].inverted
        : variantStyles[subvariant].normal;
    };

    const getTextStyle = () => {
      if (disabled) return textStyles[subvariant].disabled;
      return inverted
        ? textStyles[subvariant].inverted
        : textStyles[subvariant].normal;
    };

    // Check if className contains text color override
    const hasTextWhiteOverride =
      className?.includes("!text-white") || className?.includes("text-white");
    const hasTextBlackOverride =
      className?.includes("!text-black") || className?.includes("text-black");

    const getTextOverride = () => {
      if (hasTextWhiteOverride) return "!text-white";
      if (hasTextBlackOverride) return "!text-black";
      return getTextStyle();
    };

    return (
      <button
        ref={ref}
        className={cn("group", baseStyles, getVariantStyle(), className)}
        disabled={disabled}
        type="button"
        {...props}
      >
        <Text
          mainContentEmphasis
          className={cn("whitespace-nowrap", getTextOverride())}
          as="span"
        >
          {children}
        </Text>
      </button>
    );
  }
);
BigButton.displayName = "BigButton";

export default BigButton;
