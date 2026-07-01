import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

// twMerge resolves conflicting Tailwind utilities so a later class wins over a base default.
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
