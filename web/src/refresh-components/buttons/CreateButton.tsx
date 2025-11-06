"use client";

import { SvgPlusCircle } from "@onyx/opal";
import Button, { ButtonProps } from "@/refresh-components/buttons/Button";

export default function CreateButton({
  children,
  type = "button",
  ...props
}: ButtonProps) {
  return (
    <Button secondary leftIcon={SvgPlusCircle} type={type} {...props}>
      {children || "Create"}
    </Button>
  );
}
