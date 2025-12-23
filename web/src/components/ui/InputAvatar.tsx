"use client";

import * as React from "react";
import * as AvatarPrimitive from "@radix-ui/react-avatar";
import { cn } from "@/lib/utils";
import { wrapperClasses } from "@/refresh-components/inputs/styles";

const InputAvatar = React.forwardRef<
  React.ElementRef<typeof AvatarPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof AvatarPrimitive.Root>
>(({ className, ...props }, ref) => (
  <AvatarPrimitive.Root
    ref={ref}
    className={cn(
      "relative flex h-10 w-10 shrink-0 overflow-hidden rounded-full",
      wrapperClasses.main,
      className
    )}
    {...props}
  />
));
InputAvatar.displayName = AvatarPrimitive.Root.displayName;

export { InputAvatar as Avatar };
