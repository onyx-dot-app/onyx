"use client";

import * as React from "react";
import * as AvatarPrimitive from "@radix-ui/react-avatar";
import "@opal/components/inputs/input-avatar/styles.css";
import { cn } from "@opal/utils";

const InputAvatar = React.forwardRef<
  React.ElementRef<typeof AvatarPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof AvatarPrimitive.Root>
>(({ className, ...props }, ref) => (
  <AvatarPrimitive.Root
    ref={ref}
    className={cn(
      "relative flex h-10 w-10 shrink-0 overflow-hidden rounded-full",
      "opal-input-avatar",
      className
    )}
    {...props}
  />
));
InputAvatar.displayName = AvatarPrimitive.Root.displayName;

export default InputAvatar;
