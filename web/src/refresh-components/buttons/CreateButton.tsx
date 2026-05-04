"use client";

import { Button, type ButtonProps } from "@opal/components";
import { SvgPlusCircle } from "@opal/icons";

export type CreateButtonProps = Omit<ButtonProps, "icon">;

export default function CreateButton({
  children,
  ...props
}: CreateButtonProps) {
  return (
    <Button icon={SvgPlusCircle} prominence="secondary" {...props}>
      {children ?? "Create"}
    </Button>
  );
}
