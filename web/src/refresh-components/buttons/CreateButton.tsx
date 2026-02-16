"use client";

import Button, { ButtonProps } from "@/refresh-components/buttons/Button";
import { WithoutStyles } from "@/types";
import { SvgPlusCircle } from "@opal/icons";

export interface CreateButtonProps
  extends Omit<WithoutStyles<ButtonProps>, "leftIcon" | "rightIcon"> {
  rightIcon?: boolean;
}

export default function CreateButton({
  rightIcon,
  children,
  ...props
}: CreateButtonProps) {
  return (
    <Button
      secondary
      leftIcon={rightIcon ? undefined : SvgPlusCircle}
      rightIcon={rightIcon ? SvgPlusCircle : undefined}
      {...props}
    >
      {children ?? "Create"}
    </Button>
  );
}
