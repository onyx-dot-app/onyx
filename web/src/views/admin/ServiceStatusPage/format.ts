import type { ClusterNodeStatus } from "@/lib/service-status/types";

const MB = 1024 ** 2;
const GB = 1024 ** 3;

/** Bytes as GB with one decimal below 100 GB, whole GB above. */
export function toGb(bytes: number): string {
  const gb = bytes / GB;
  return gb >= 100 ? gb.toFixed(0) : gb.toFixed(1);
}

/** A size and its unit: MB below 1 GB, else GB. Pass scaleBytes to use the
 *  unit of another size, so "used / total" shares one unit. */
export interface SizeParts {
  value: string;
  unit: "MB" | "GB";
}

export function toSize(bytes: number, scaleBytes: number = bytes): SizeParts {
  if (scaleBytes < GB) {
    return { value: (bytes / MB).toFixed(bytes < 10 * MB ? 1 : 0), unit: "MB" };
  }
  return { value: toGb(bytes), unit: "GB" };
}

/** Not rounded, so a bar's color matches the backend's issues at a limit. */
export function percent(part: number, whole: number): number {
  return whole > 0 ? (100 * part) / whole : 0;
}

export function diskPercent(node: ClusterNodeStatus): number {
  return percent(node.disk_used_bytes, node.disk_total_bytes);
}

export function vectorPercent(node: ClusterNodeStatus): number {
  return percent(node.vector_bytes, node.file_cache_bytes);
}

/** The bar's color at the backend's warning and critical limits. */
export function barColor(
  value: number,
  warning: number,
  critical: number
): "green" | "amber" | "red" {
  if (value >= critical) return "red";
  if (value >= warning) return "amber";
  return "green";
}

export const SIZING_GUIDE_URL =
  "https://docs.onyx.app/deployment/getting_started/resourcing";

/** A count in compact notation, split into the number and its suffix ("24.1", "M"). */
export function compactParts(value: number, locale: string): [string, string] {
  const parts = new Intl.NumberFormat(locale, {
    notation: "compact",
    maximumFractionDigits: 1,
  }).formatToParts(value);
  const suffix = parts
    .filter((part) => part.type === "compact")
    .map((part) => part.value)
    .join("");
  const number = parts
    .filter((part) => part.type !== "compact" && part.type !== "literal")
    .map((part) => part.value)
    .join("");
  return [number, suffix];
}
