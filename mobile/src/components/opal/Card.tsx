import type { ReactNode } from "react";
import { View, type ViewProps } from "react-native";

import { cn } from "@/lib/cn";

interface CardProps extends Omit<ViewProps, "children"> {
  className?: string;
  children?: ReactNode;
}

// Static token classes so NativeWind compiles them; className passthrough merged via cn.
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
