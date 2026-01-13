"use client";

import React, { useState } from "react";
import Popover from "@/refresh-components/Popover";

export interface SimplePopoverProps
  extends React.ComponentPropsWithoutRef<typeof Popover.Content> {
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
      <Popover.Trigger asChild>
        <div>{typeof trigger === "function" ? trigger(open) : trigger}</div>
      </Popover.Trigger>
      <Popover.Content align="start" side="top" {...rest} />
    </Popover>
  );
}
