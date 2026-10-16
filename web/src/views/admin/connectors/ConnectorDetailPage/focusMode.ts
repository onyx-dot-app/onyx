import { cn } from "@opal/utils";

/** Fades content back while a run row's stage or checks popover is open. */
export function focusDimClass(dimmed: boolean): string {
  return cn("transition-opacity", dimmed && "opacity-50");
}
