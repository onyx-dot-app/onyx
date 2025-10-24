"use client";

import React from "react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";

export interface SimplePopoverProps
  extends React.ComponentPropsWithoutRef<typeof PopoverContent> {
  trigger: React.ReactNode;
}

export default function SimplePopover({
  trigger,
  ...rest
}: SimplePopoverProps) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <div>{trigger}</div>
      </PopoverTrigger>
      <PopoverContent align="start" side="top" {...rest}></PopoverContent>
    </Popover>
  );
}
