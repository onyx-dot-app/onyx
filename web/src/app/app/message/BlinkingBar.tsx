import { cn } from "@opal/utils";

export function BlinkingBar({ addMargin = false }: { addMargin?: boolean }) {
  return (
    <span
      className={cn(
        "animate-pulse flex-none bg-theme-primary-05 relative top-[0.15rem] inline-block w-2 h-4",
        addMargin && "ml-1"
      )}
    ></span>
  );
}
