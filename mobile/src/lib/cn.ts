import clsx, { type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

// Mirrors the web Opal `cn` helper (merge + de-dup conflicting NativeWind utils).
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
