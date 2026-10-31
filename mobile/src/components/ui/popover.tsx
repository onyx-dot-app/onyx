/*
 * Anchored floating panel, the RN counterpart of Opal's Popover
 * (web/lib/opal/src/components/popover/). Use this instead of `Sheet` when the options belong
 * visually to the control that opened them rather than to the screen.
 *
 * It draws through the app-wide PortalHost in app/_layout.tsx, which must stay mounted. Open
 * state is internal: the native primitive has no controlled `open` prop the way Opal does, so
 * wrap a row in `Popover.Close` to dismiss the panel when that row is pressed.
 */
import type { ReactNode } from "react";
import { StyleSheet } from "react-native";
import * as PopoverPrimitive from "@rn-primitives/popover";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { cn } from "@/lib/utils";

// Mirrors web's `shadow-box-02` token, flattened to the single shadow layer RN can draw.
const SHADOW_BOX_02 = {
  shadowColor: "#000000",
  shadowOffset: { width: 0, height: 2 },
  shadowOpacity: 0.12,
  shadowRadius: 24,
  elevation: 8,
} as const;

const EDGE_PADDING = 8;

interface PopoverProps {
  onOpenChange?: (open: boolean) => void;
  children: ReactNode;
}

function Popover({ onOpenChange, children }: PopoverProps) {
  return (
    <PopoverPrimitive.Root onOpenChange={onOpenChange}>
      {children}
    </PopoverPrimitive.Root>
  );
}

interface PopoverTriggerProps {
  children: ReactNode;
  className?: string;
  accessibilityLabel?: string;
}

/*
 * Pass presentational children only. The trigger is itself the pressable, so handing it another
 * one (a Button, a SelectButton) means the inner control swallows the press and the panel never
 * opens. It also has to stay a real pressable for the primitive to measure it and anchor to it.
 */
function PopoverTrigger({
  children,
  className,
  accessibilityLabel,
}: PopoverTriggerProps) {
  return (
    <PopoverPrimitive.Trigger
      accessibilityLabel={accessibilityLabel}
      className={className}
    >
      {children}
    </PopoverPrimitive.Trigger>
  );
}

interface PopoverCloseProps {
  children: ReactNode;
}

// `asChild` keeps the caller's own row as the pressable; wrapping would nest two of them.
function PopoverClose({ children }: PopoverCloseProps) {
  return <PopoverPrimitive.Close asChild>{children}</PopoverPrimitive.Close>;
}

interface PopoverContentProps {
  children: ReactNode;
  side?: "top" | "bottom";
  align?: "start" | "center" | "end";
  sideOffset?: number;
  className?: string;
}

function PopoverContent({
  children,
  side = "bottom",
  align = "center",
  sideOffset = 4,
  className,
}: PopoverContentProps) {
  const insets = useSafeAreaInsets();

  return (
    <PopoverPrimitive.Portal>
      {/* The overlay has to be absolutely positioned: the portal host sits in the root layout, so
          a flex-sized one would take real space there and squeeze the screen underneath it. */}
      <PopoverPrimitive.Overlay style={StyleSheet.absoluteFill}>
        <PopoverPrimitive.Content
          side={side}
          align={align}
          sideOffset={sideOffset}
          insets={{
            top: insets.top + EDGE_PADDING,
            bottom: insets.bottom + EDGE_PADDING,
            left: insets.left + EDGE_PADDING,
            right: insets.right + EDGE_PADDING,
          }}
          style={SHADOW_BOX_02}
          // Roomier than Opal's 4px inset, because these rows are touch targets, not hover targets.
          className={cn(
            "rounded-12 border border-border-01 bg-background-neutral-00 p-8",
            className,
          )}
        >
          {children}
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Overlay>
    </PopoverPrimitive.Portal>
  );
}

Popover.Trigger = PopoverTrigger;
Popover.Content = PopoverContent;
Popover.Close = PopoverClose;

export { Popover, type PopoverProps, type PopoverContentProps };
