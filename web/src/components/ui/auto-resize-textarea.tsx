import * as React from "react";
import { cn } from "@/lib/utils";
import { Textarea, TextareaProps } from "@/components/ui/textarea";

export interface AutoResizeTextareaProps
  extends Omit<TextareaProps, "value" | "onChange"> {
  value: string;
  onChange: (value: string) => void;
}

export const AutoResizeTextarea = React.forwardRef<
  HTMLTextAreaElement,
  AutoResizeTextareaProps
>(({ value, onChange, className, ...props }, forwardedRef) => {
  const innerRef = React.useRef<HTMLTextAreaElement | null>(null);

  const setRefs = React.useCallback(
    (node: HTMLTextAreaElement | null) => {
      innerRef.current = node;
      if (typeof forwardedRef === "function") {
        forwardedRef(node);
      } else if (forwardedRef) {
        forwardedRef.current = node;
      }
    },
    [forwardedRef]
  );

  const resizeTextarea = React.useCallback(() => {
    if (!innerRef.current) {
      return;
    }
    const textarea = innerRef.current;
    textarea.style.height = "auto";
    textarea.style.height = `${textarea.scrollHeight}px`;
  }, []);

  React.useEffect(() => {
    resizeTextarea();
  }, [resizeTextarea, value]);

  return (
    <Textarea
      {...props}
      className={cn("min-h-[3rem] resize-none", className)}
      ref={setRefs}
      value={value}
      onChange={(event) => {
        onChange(event.target.value);
        resizeTextarea();
      }}
    />
  );
});

AutoResizeTextarea.displayName = "AutoResizeTextarea";
