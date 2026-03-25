import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import type { RichStr } from "@opal/types";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Wraps a string for inline markdown parsing by `Text` and other Opal components. */
export function markdown(content: string): RichStr {
  return { __brand: "RichStr", raw: content };
}
