"use client";

import "./styles.css";

import * as RadixPopover from "@radix-ui/react-popover";

export function Popover({
  open,
  onOpenChange,
  content,
  popover,
  side,
  align,
  contentClassName,
  sideOffset,
  alignOffset,
  matchWidth,
  requiresContentPadding,
  triggerMaxWidth,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  content: JSX.Element;
  popover: JSX.Element;
  side?: "top" | "right" | "bottom" | "left";
  align?: "start" | "center" | "end";
  contentClassName?: string;
  sideOffset?: number;
  alignOffset?: number;
  matchWidth?: boolean;
  requiresContentPadding?: boolean;
  triggerMaxWidth?: boolean;
}) {
  /* 
  This Popover is needed when we want to put a popup / dropdown in a component
  with `overflow-hidden`. This is because the Radix Popover uses `absolute` positioning
  outside of the component's container.
  */
  if (!open) {
    return content;
  }

  return (
    <RadixPopover.Root open={open} onOpenChange={onOpenChange}>
      <RadixPopover.Trigger
        style={triggerMaxWidth ? { width: "100%" } : {}}
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
        }}
      >
        {/* NOTE: this weird `-mb-1.5` is needed to offset the Anchor, otherwise 
          the content will shift up by 1.5px when the Popover is open. */}
        {open ? (
          <div className={requiresContentPadding ? "-mb-1.5" : ""}>
            {content}
          </div>
        ) : (
          content
        )}
      </RadixPopover.Trigger>
      <RadixPopover.Portal>
        <RadixPopover.Content
          className={`
            PopoverContent z-[100] 
            ${contentClassName}
            ${matchWidth ? " PopoverContentMatchWidth" : ""}
          `}
          asChild
          side={side}
          align={align}
          sideOffset={sideOffset}
          alignOffset={alignOffset}
          onClick={(e) => e.stopPropagation()}
        >
          {popover}
        </RadixPopover.Content>
      </RadixPopover.Portal>
    </RadixPopover.Root>
  );
}
