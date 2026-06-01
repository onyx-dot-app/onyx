import type { ReactNode } from "react";
import { View, type ViewProps } from "react-native";

import { cn } from "@/lib/cn";

interface CardProps extends Omit<ViewProps, "children"> {
  /** Extra classes merged after the base card styling. */
  className?: string;
  children?: ReactNode;
}

/**
 * Themed container surface. Uses STATIC token classes (background, border,
 * radius) so NativeWind compiles them; a `className` passthrough is merged via
 * `cn`.
 */
function Card({ className, children, ...rest }: CardProps) {
  return (
    <View
      {...rest}
      className={cn(
        "bg-background-neutral-01 border border-border-02 rounded-[12px] p-4",
        className,
      )}
    >
      {children}
    </View>
  );
}

export { Card, type CardProps };
