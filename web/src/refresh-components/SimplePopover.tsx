"use client";

import React, { useState } from "react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";

export interface SimplePopoverProps
  extends React.ComponentPropsWithoutRef<typeof PopoverContent> {
  onOpenChange?: (open: boolean) => void;
  trigger: React.ReactNode | ((open: boolean) => React.ReactNode);
}

export default function SimplePopover({
  trigger,
  onOpenChange,
  ...rest
}: SimplePopoverProps) {
  const [open, setOpen] = useState(false);

  function handleOnOpenChange(state: boolean) {
    setOpen(state);
    onOpenChange?.(state);
  }

  return (
    <Popover open={open} onOpenChange={handleOnOpenChange}>
      <PopoverTrigger asChild>
        <div>{typeof trigger === "function" ? trigger(open) : trigger}</div>
      </PopoverTrigger>
      <PopoverContent align="start" side="top" {...rest} />
    </Popover>
  );
}
