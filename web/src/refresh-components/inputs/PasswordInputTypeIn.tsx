"use client";

import React, { useState } from "react";
import InputTypeIn, {
  InputTypeInProps,
} from "@/refresh-components/inputs/InputTypeIn";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgEye from "@/icons/eye";
import SvgEyeClosed from "@/icons/eye-closed";
import { noProp } from "@/lib/utils";

export interface PasswordInputTypeInProps
  extends Omit<InputTypeInProps, "type" | "rightSection"> {}

export default function PasswordInputTypeIn({
  disabled,
  ...props
}: PasswordInputTypeInProps) {
  const [isPasswordVisible, setIsPasswordVisible] = useState(false);

  const rightSection = (
    <>
      <IconButton
        icon={isPasswordVisible ? SvgEye : SvgEyeClosed}
        disabled={disabled}
        onClick={noProp(() => setIsPasswordVisible((v) => !v))}
        type="button"
        internal
        aria-label={isPasswordVisible ? "Hide password" : "Show password"}
      />
    </>
  );

  return (
    <InputTypeIn
      {...props}
      disabled={disabled}
      type={isPasswordVisible ? "text" : "password"}
      rightSection={rightSection}
    />
  );
}
