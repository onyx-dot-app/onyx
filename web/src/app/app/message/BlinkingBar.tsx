import { cn } from "@opal/utils";
import { STREAMING_CURSOR_CLASS_NAME } from "@/lib/rehypeStreamingCursor";

export function BlinkingBar({ addMargin = false }: { addMargin?: boolean }) {
  return (
    <span
      aria-hidden
      className={cn(STREAMING_CURSOR_CLASS_NAME, addMargin && "ms-1")}
    ></span>
  );
}
