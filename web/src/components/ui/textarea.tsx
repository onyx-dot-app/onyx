import * as React from "react";

import { cn } from "@/lib/utils";

export interface TextareaProps
  extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {}

const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, ...props }, ref) => {
    return (
      <textarea
        className={cn(
          [
            "flex",
            "min-h-[80px]",
            "w-full",
            "rounded-md",
            "border",
            "border-background-200",
            "bg-white",
            "px-3",
            "py-2",
            "text-sm",
            "ring-offset-white",
            "placeholder:text-neutral-500",
            // "focus-visible:outline-none",
            // "focus-visible:ring-2",
            // "focus-visible:ring-neutral-950",
            // "focus-visible:ring-offset-2",
            "disabled:cursor-not-allowed",
            "disabled:opacity-50",
          ].join(" "),
          className
        )}
        ref={ref}
        {...props}
      />
    );
  }
);
Textarea.displayName = "Textarea";

export { Textarea };
