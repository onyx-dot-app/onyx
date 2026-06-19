import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

// Single class-merge helper for every UI component (mirrors web's @/lib/utils `cn`).
// clsx flattens conditionals/arrays; twMerge resolves conflicting Tailwind utilities
// so a later class (e.g. an explicit `text-text-02`) wins over a base default.
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
