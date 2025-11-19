"use client";

import React, { useState } from "react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";

export interface SimplePopoverProps
  extends Omit<
    React.ComponentPropsWithoutRef<typeof PopoverContent>,
    "children"
  > {
  trigger: React.ReactNode | ((open: boolean) => React.ReactNode);
  children: React.ReactNode | ((close: () => void) => React.ReactNode);
}

export default function SimplePopover({
  trigger,
  children,
  ...rest
}: SimplePopoverProps) {
  const [open, setOpen] = useState(false);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <div>{typeof trigger === "function" ? trigger(open) : trigger}</div>
      </PopoverTrigger>
      <PopoverContent align="start" side="top" {...rest}>
        {typeof children === "function"
          ? children(() => setOpen(false))
          : children}
      </PopoverContent>
    </Popover>
  );
}
