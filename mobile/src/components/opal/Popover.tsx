import type { ReactNode } from "react";
import { StyleSheet } from "react-native";
import * as PopoverPrimitive from "@rn-primitives/popover";

import { cn } from "@/lib/cn";

// Requires a <PortalHost /> (from @rn-primitives/portal) near the app root.

type PopoverRootProps = React.ComponentProps<typeof PopoverPrimitive.Root>;

type PopoverTriggerRef = PopoverPrimitive.TriggerRef;

interface PopoverContentProps
  extends Omit<React.ComponentProps<typeof PopoverPrimitive.Content>, "children"> {
  className?: string;
  children?: ReactNode;
  sideOffset?: number;
}

// Pre-themed surface bundling Portal + a transparent dismiss Overlay (outside press closes).
function PopoverContent({
  className,
  children,
  sideOffset = 6,
  ...rest
}: PopoverContentProps) {
  return (
    <PopoverPrimitive.Portal>
      {/* Absolute fill, NOT flex:1: PortalHost renders into a bare Fragment in normal flow and
          the Overlay applies no positioning, so flex:1 would split the screen instead of covering
          it. Content positions absolutely against this Overlay in screen coords, so it must sit at
          (0,0) and cover the screen (matches the opal Modal overlay's absolute inset-0). */}
      <PopoverPrimitive.Overlay style={StyleSheet.absoluteFill}>
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

function Popover(props: PopoverRootProps) {
  return <PopoverPrimitive.Root {...props} />;
}

Popover.Trigger = PopoverPrimitive.Trigger;
Popover.Content = PopoverContent;
Popover.Close = PopoverPrimitive.Close;

const PopoverPrimitiveExport = PopoverPrimitive;

export {
  Popover,
  PopoverContent,
  PopoverPrimitiveExport as PopoverPrimitive,
  type PopoverContentProps,
  type PopoverRootProps,
  type PopoverTriggerRef,
};
