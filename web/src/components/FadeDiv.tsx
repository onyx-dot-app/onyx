import React from "react";
import { cn } from "@/lib/utils";

interface FadeDivProps {
  className?: string;
  fadeClassName?: string;
  footerClassName?: string;
  children: React.ReactNode;
  direction?: "top" | "bottom";
  height?: number | string;
}

const FadeDiv: React.FC<FadeDivProps> = ({
  className,
  fadeClassName,
  footerClassName,
  children,
  direction = "top",
  height,
}) => {
  const isBottom = direction === "bottom";

  // Bottom direction: simple container with fade overlay
  if (isBottom) {
    return (
      <div
        className={cn("relative w-full overflow-hidden", className)}
        style={height ? { maxHeight: height } : undefined}
      >
        {children}
        <div
          className={cn(
            "absolute inset-x-0 bottom-0 h-8 bg-gradient-to-t from-background to-transparent pointer-events-none",
            fadeClassName
          )}
        />
      </div>
    );
  }

  // Top direction: original behavior
  return (
    <div className={cn("relative w-full", className)}>
      <div
        className={cn(
          "absolute inset-x-0 -top-8 h-8 bg-gradient-to-b from-transparent to-background pointer-events-none",
          fadeClassName
        )}
      />
      <div
        className={cn(
          "flex items-center justify-end w-full pt-2 px-2",
          footerClassName
        )}
      >
        {children}
      </div>
    </div>
  );
};

export default FadeDiv;
