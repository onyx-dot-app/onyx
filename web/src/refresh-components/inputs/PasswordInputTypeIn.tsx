"use client";

import { useState } from "react";
import InputTypeIn, {
  InputTypeInProps,
} from "@/refresh-components/inputs/InputTypeIn";
import IconButton from "@/refresh-components/buttons/IconButton";
import { noProp } from "@/lib/utils";
import { SvgEye, SvgEyeClosed } from "@opal/icons";

export interface PasswordInputTypeInProps
  extends Omit<InputTypeInProps, "type" | "rightSection"> {}

export default function PasswordInputTypeIn({
  disabled,
  ...props
}: PasswordInputTypeInProps) {
  const [isPasswordVisible, setIsPasswordVisible] = useState(false);

  return (
    <InputTypeIn
      {...props}
      disabled={disabled}
      type={isPasswordVisible ? "text" : "password"}
      rightSection={
        <IconButton
          icon={isPasswordVisible ? SvgEye : SvgEyeClosed}
          disabled={disabled}
          onClick={noProp(() => setIsPasswordVisible((v) => !v))}
          type="button"
          internal
          aria-label={isPasswordVisible ? "Hide password" : "Show password"}
        />
      }
    />
  );
}
