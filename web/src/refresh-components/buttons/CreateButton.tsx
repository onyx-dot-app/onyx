"use client";

import Button, { ButtonProps } from "@/refresh-components/buttons/Button";
import SvgPlusCircle from "@/icons/plus-circle";

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
