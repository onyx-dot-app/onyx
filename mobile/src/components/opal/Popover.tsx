import type { ReactNode } from "react";
import * as PopoverPrimitive from "@rn-primitives/popover";

import { cn } from "@/lib/cn";

// ---------------------------------------------------------------------------
// Popover — a themed anchored popover built on @rn-primitives/popover.
//
// API: compound. The trigger anchors the floating content; positioning is
// handled by rn-primitives.
//
//   <Popover>
//     <Popover.Trigger asChild>
//       <Button>Open</Button>
//     </Popover.Trigger>
//     <Popover.Content>
//       ...content...
//     </Popover.Content>
//   </Popover>
//
// `Popover` is the Root. `Popover.Content` is a pre-themed card; it already
// wraps Portal + Overlay (so an outside press dismisses it) — callers only
// supply children. For full control, the raw parts are on `PopoverPrimitive`.
//
// Requires a <PortalHost /> (from @rn-primitives/portal) near the app root.
// ---------------------------------------------------------------------------

type PopoverRootProps = React.ComponentProps<typeof PopoverPrimitive.Root>;

interface PopoverContentProps
  extends Omit<React.ComponentProps<typeof PopoverPrimitive.Content>, "children"> {
  /** Extra classes merged onto the content card. */
  className?: string;
  children?: ReactNode;
  /** Distance (px) between trigger and content. Default: 6. */
  sideOffset?: number;
}

/**
 * Pre-themed popover surface: a `background-neutral-00` rounded, bordered,
 * padded card. Bundles Portal + a transparent dismiss Overlay so an outside
 * press closes the popover.
 */
function PopoverContent({
  className,
  children,
  sideOffset = 6,
  ...rest
}: PopoverContentProps) {
  return (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Overlay style={{ flex: 1 }}>
        <PopoverPrimitive.Content
          sideOffset={sideOffset}
          {...rest}
          className={cn(
            "min-w-[160px] rounded-[12px] border border-border-02 bg-background-neutral-00 p-3",
            className,
          )}
        >
          {children}
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Overlay>
    </PopoverPrimitive.Portal>
  );
}

/**
 * Popover root. Compose with `Popover.Trigger` and `Popover.Content`.
 */
function Popover(props: PopoverRootProps) {
  return <PopoverPrimitive.Root {...props} />;
}

Popover.Trigger = PopoverPrimitive.Trigger;
Popover.Content = PopoverContent;
Popover.Close = PopoverPrimitive.Close;

/** Raw, unstyled rn-primitives popover parts for full control. */
const PopoverPrimitiveExport = PopoverPrimitive;

export {
  Popover,
  PopoverContent,
  PopoverPrimitiveExport as PopoverPrimitive,
  type PopoverContentProps,
  type PopoverRootProps,
};
