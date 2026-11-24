import type { ClusterNodeStatus } from "@/lib/service-status/types";

const MB = 1024 ** 2;
const GB = 1024 ** 3;

function fixed(value: number, digits: number, locale: string): string {
  return new Intl.NumberFormat(locale, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
}

/** A size and its unit: MB below 1 GB, else GB. Pass scaleBytes to use the
 *  unit of another size, so "used / total" shares one unit. */
export interface SizeParts {
  value: string;
  unit: "MB" | "GB";
}

/** One decimal below 10 MB or 100 GB, whole numbers above. */
export function toSize(
  bytes: number,
  locale: string,
  scaleBytes: number = bytes
): SizeParts {
  if (scaleBytes < GB) {
    return {
      value: fixed(bytes / MB, bytes < 10 * MB ? 1 : 0, locale),
      unit: "MB",
    };
  }
  const gb = bytes / GB;
  return { value: fixed(gb, gb >= 100 ? 0 : 1, locale), unit: "GB" };
}

/** Not rounded, so a bar's color matches the backend's issues at a limit. */
export function percent(part: number, whole: number): number {
  return whole > 0 ? (100 * part) / whole : 0;
}

export function diskPercent(node: ClusterNodeStatus): number {
  return percent(node.disk_used_bytes, node.disk_total_bytes);
}

/** Vectors with no file cache to hold them count as full, as in the backend. */
export function vectorPercent(node: ClusterNodeStatus): number {
  if (node.file_cache_bytes <= 0) return node.vector_bytes > 0 ? 100 : 0;
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

// OpenSearch names a node after its host when no name is set: a container
// or instance hash, which means nothing to an admin.
const GENERATED_NAME = /^[0-9a-f]{12,}$/i;

/**
 * A node's name for the page: its own, or "Node N" when OpenSearch generated
 * the name from the host. number is the node's place in the node list, so
 * the data node rows and the issues name a node the same way.
 */
export function nodeLabel(
  name: string,
  number: number,
  unnamed: (number: number) => string
): string {
  return GENERATED_NAME.test(name) ? unnamed(number) : name;
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
