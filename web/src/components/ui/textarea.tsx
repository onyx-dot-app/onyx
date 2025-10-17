import * as React from "react";

import { cn } from "@/lib/utils";

export interface TextareaProps
  extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {}

const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, ...props }, ref) => {
    return (
      <textarea
        className={cn(
          "flex",
          "min-h-[80px]",
          "w-full",
          "rounded-md",
          "border",
          "border-border",
          "bg-background",
          "px-3",
          "py-2",
          "text-sm",
          "text-foreground",
          "ring-offset-background",
          "placeholder:text-muted-foreground",
          "focus-visible:outline-none",
          "focus-visible:ring-2",
          "focus-visible:ring-border",
          "focus-visible:ring-offset-2",
          "focus-visible:ring-offset-background",
          "disabled:cursor-not-allowed",
          "disabled:opacity-50",
          "dark:border-border-dark",
          "dark:text-foreground",
          "dark:focus-visible:ring-border-dark",
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
