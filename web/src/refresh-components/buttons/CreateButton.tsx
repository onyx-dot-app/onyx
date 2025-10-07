"use client";

import Button, { ButtonProps } from "@/refresh-components/buttons/Button";
import SvgPlusCircle from "@/icons/plus-circle";

export default function CreateButton({
  href,
  onClick,
  children,
  ...props
}: ButtonProps) {
  return (
    <Button
      secondary
      onClick={onClick}
      leftIcon={SvgPlusCircle}
      href={href}
      {...props}
    >
      {children || "Create"}
    </Button>
  );
}
