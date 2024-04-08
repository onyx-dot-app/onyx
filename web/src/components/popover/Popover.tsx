"use client";

import * as RadixPopover from "@radix-ui/react-popover";

export function Popover({
  open,
  onOpenChange,
  content,
  popover,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  content: JSX.Element;
  popover: JSX.Element;
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
      <RadixPopover.Trigger>
        {/* NOTE: this weird `-mb-1.5` is needed to offset the Anchor, otherwise 
          the content will shift up by 1.5px when the Popover is open. */}
        {open ? <div className="-mb-1.5">{content}</div> : content}
      </RadixPopover.Trigger>
      <RadixPopover.Anchor />
      <RadixPopover.Portal>
        <RadixPopover.Content>{popover}</RadixPopover.Content>
      </RadixPopover.Portal>
    </RadixPopover.Root>
  );
}
