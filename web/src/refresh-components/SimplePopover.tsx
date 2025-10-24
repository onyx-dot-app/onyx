"use client";

import React, { useState } from "react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";

export interface SimplePopoverProps
  extends React.ComponentPropsWithoutRef<typeof PopoverContent> {
  trigger: React.ReactNode | ((open: boolean) => React.ReactNode);
}

export default function SimplePopover({
  trigger,
  ...rest
}: SimplePopoverProps) {
  const [open, setOpen] = useState(false);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <div>{typeof trigger === "function" ? trigger(open) : trigger}</div>
      </PopoverTrigger>
      <PopoverContent align="start" side="top" {...rest} />
    </Popover>
  );
}
