import { cn } from "@/lib/utils";

export function BlinkingBar({ addMargin = false }: { addMargin?: boolean }) {
  return (
    <span
      className={cn(
        "animate-pulse flex-none bg-theme-primary-05 relative top-[0.25rem] inline-block w-[0.5em] h-[1.25em]",
        addMargin && "ml-1"
      )}
    ></span>
  );
}
