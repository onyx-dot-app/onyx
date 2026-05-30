import clsx, { type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Merge conditional class names and de-duplicate conflicting Tailwind/NativeWind
 * utilities. Mirrors the web Opal `cn` helper so component class composition is
 * consistent across platforms.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
