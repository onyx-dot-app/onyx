"use client";

import * as React from "react";
import * as AvatarPrimitive from "@radix-ui/react-avatar";
import "@opal/components/inputs/input-avatar/styles.css";
import { cn } from "@opal/utils";
import type { RichStr } from "@opal/types";
import { InputTooltip } from "@opal/components/inputs/disabled";

type InputAvatarProps = React.ComponentPropsWithoutRef<
  typeof AvatarPrimitive.Root
> & {
  /** Shown on hover. A disabled row's reason replaces it. */
  tooltip?: string | RichStr;
};

/**
 * Inside `InputHorizontal` or `InputVertical` with a `disabledTooltip`, that
 * reason shows on it while the row is disabled. It has no disabled state.
 */
const InputAvatar = React.forwardRef<
  React.ElementRef<typeof AvatarPrimitive.Root>,
  InputAvatarProps
>(({ className, tooltip, ...props }, ref) => (
  <InputTooltip tooltip={tooltip}>
    <AvatarPrimitive.Root
      ref={ref}
      className={cn(
        "relative flex h-10 w-10 shrink-0 overflow-hidden rounded-full",
        "opal-input-avatar",
        className
      )}
      {...props}
    />
  </InputTooltip>
));
InputAvatar.displayName = AvatarPrimitive.Root.displayName;

export default InputAvatar;
