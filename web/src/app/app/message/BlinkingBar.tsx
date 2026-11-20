import { cn } from "@opal/utils";

export function BlinkingBar({ addMargin = false }: { addMargin?: boolean }) {
  return (
    <span
      aria-hidden
      className={cn(
        "animate-pulse motion-reduce:animate-none flex-none bg-text-04 rounded-xs relative top-[0.2rem] inline-block w-1.5 h-3.5",
        addMargin && "ms-1"
      )}
    ></span>
  );
}
