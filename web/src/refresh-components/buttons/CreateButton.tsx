"use client";

import Button, { ButtonProps } from "@/refresh-components/buttons/Button";
import SvgPlusCircle from "@/icons/plus-circle";

export default function CreateButton({ children, ...props }: ButtonProps) {
  return (
    <Button secondary leftIcon={SvgPlusCircle} {...props}>
      {children ?? "Create"}
    </Button>
  );
}
