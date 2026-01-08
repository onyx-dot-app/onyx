"use client";

import React from "react";
import { cn } from "@/lib/utils";
import type { IconProps } from "@opal/types";

export interface SquareButtonProps
  extends Omit<React.ComponentPropsWithoutRef<"button">, "children"> {
  transient?: boolean;
  icon: React.FunctionComponent<IconProps>;
}

const SquareButton = React.forwardRef<HTMLButtonElement, SquareButtonProps>(
  ({ transient = false, icon: Icon, className, ...props }, ref) => {
    return (
      <button
        ref={ref}
        type="button"
        data-state={transient ? "transient" : "normal"}
        className={cn("square-button rounded-08", className)}
        {...props}
      >
        <Icon className="h-5 w-5" />
      </button>
    );
  }
);
SquareButton.displayName = "SquareButton";

export default SquareButton;
