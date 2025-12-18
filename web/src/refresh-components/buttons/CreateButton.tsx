"use client";

import Button, { ButtonProps } from "@/refresh-components/buttons/Button";
import { SvgPlusCircle } from "@opal/icons";
export default function CreateButton({ children, ...props }: ButtonProps) {
  return (
    <Button secondary leftIcon={SvgPlusCircle} {...props}>
      {children ?? "Create"}
    </Button>
  );
}
