import React from "react";
import { cn } from "@/lib/utils";

interface FadeDivProps {
  className?: string;
  fadeClassName?: string;
  footerClassName?: string;
  children: React.ReactNode;
}

const FadeDiv: React.FC<FadeDivProps> = ({
  className,
  fadeClassName,
  footerClassName,
  children,
}) => (
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

export default FadeDiv;
