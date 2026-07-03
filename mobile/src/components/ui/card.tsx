import type { ReactNode } from "react";
import { Pressable, View } from "react-native";

import { cn } from "@/lib/utils";

type CardVariant = "primary" | "secondary" | "tertiary" | "borderless";

const VARIANT_CLASSES: Record<CardVariant, string> = {
  primary: "border border-border-01 bg-background-tint-00",
  secondary: "border border-border-01",
  tertiary: "border border-dashed border-border-01",
  borderless: "bg-background-tint-00",
};

interface CardProps {
  variant?: CardVariant;
  onPress?: () => void;
  disabled?: boolean;
  className?: string;
  children: ReactNode;
}

// Clipped, rounded container with a variant background/border. Static by default; pass
// `onPress` to make the whole card tappable — touch has no hover, so press feedback is a
// subtle active background rather than a hover shadow.
function Card({
  variant = "primary",
  onPress,
  disabled = false,
  className,
  children,
}: CardProps) {
  const base = cn(
    "w-full overflow-hidden rounded-16 p-16",
    VARIANT_CLASSES[variant],
    disabled && "opacity-50",
    className,
  );

  if (onPress) {
    return (
      <Pressable
        onPress={onPress}
        disabled={disabled}
        accessibilityRole="button"
        className={cn(base, !disabled && "active:bg-background-tint-01")}
      >
        {children}
      </Pressable>
    );
  }

  return <View className={base}>{children}</View>;
}

export { Card, type CardProps, type CardVariant };
