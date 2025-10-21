"use client";

import Button, { ButtonProps } from "@/refresh-components/buttons/Button";
import SvgPlusCircle from "@/icons/plus-circle";

export default function CreateButton({
  href,
  onClick,
  children,
  type = "button",
  ...props
}: ButtonProps) {
  return (
    <Button
      secondary
      onClick={onClick}
      leftIcon={SvgPlusCircle}
      href={href}
      type={type}
      {...props}
    >
      {children || "Create"}
    </Button>
  );
}
