import type { DocumentTypeCount } from "@/lib/connectors/types";

// MIME types whose usual extension is not their subtype.
const EXTENSION_BY_MIME = new Map([
  ["text/plain", "txt"],
  ["text/markdown", "md"],
  ["text/javascript", "js"],
  ["image/jpeg", "jpg"],
  ["image/svg+xml", "svg"],
  ["application/msword", "doc"],
  ["application/vnd.ms-excel", "xls"],
  ["application/vnd.ms-powerpoint", "ppt"],
  [
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "docx",
  ],
  ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"],
  [
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "pptx",
  ],
  ["application/vnd.google-apps.document", "gdoc"],
  ["application/vnd.google-apps.spreadsheet", "gsheet"],
  ["application/vnd.google-apps.presentation", "gslides"],
  ["application/x-zip-compressed", "zip"],
]);

/** A MIME type's label: its usual extension upper-cased, else its subtype. */
export function documentTypeLabel(mimeType: string): string {
  const base = (mimeType.split(";")[0] ?? "").trim().toLowerCase();
  const extension = EXTENSION_BY_MIME.get(base);
  if (extension !== undefined) return extension.toUpperCase();
  const subtype = base.split("/")[1] || base;
  return subtype.replace(/^(x-|vnd\.)/, "").toUpperCase();
}

/** The type colors in the order the largest types take them; class names stay whole for Tailwind. */
const TYPE_COLORS = [
  "bg-chart-category-blue-2",
  "bg-chart-category-cyan-1",
  "bg-chart-category-amber-2",
  "bg-chart-category-green-2",
  "bg-chart-category-cyan-2",
  "bg-chart-category-amber-1",
  "bg-chart-category-orange-2",
  "bg-chart-category-pink-2",
  "bg-chart-category-purple-2",
  "bg-chart-category-purple-1",
  "bg-chart-category-pink-1",
] as const;

// Not a type, so a neutral rather than a twelfth category color.
const OTHER_COLOR = "bg-border-03";

/** The slice that holds every type past the eleventh. */
export const OTHER_DOCUMENT_TYPE = "other";

export interface DocumentTypeSlice {
  /** The MIME type, or `OTHER_DOCUMENT_TYPE`. */
  key: string;
  count: number;
  /** Null unless every document in the slice reports a size, so a partial sum never shows. */
  sizeBytes: number | null;
  colorClass: string;
}

function fullSize(type: DocumentTypeCount): number | null {
  return type.sized_count === type.count ? (type.size_bytes ?? 0) : null;
}

/** The total size of `types`, or null when any document lacks one. */
export function totalSize(types: DocumentTypeCount[]): number | null {
  let total = 0;
  for (const type of types) {
    const size = fullSize(type);
    if (size === null) return null;
    total += size;
  }
  return total;
}

function colorOf(
  assigned: Map<string, string>,
  taken: Set<string>,
  key: string
): string {
  const kept = assigned.get(key);
  if (kept !== undefined) return kept;
  // At most eleven types show, so a color is always free.
  const free = TYPE_COLORS.find((color) => !taken.has(color)) ?? OTHER_COLOR;
  taken.add(free);
  // A type that left the top eleven gives its color up.
  for (const [other, color] of assigned) {
    if (color === free) assigned.delete(other);
  }
  assigned.set(key, free);
  return free;
}

/** Each pair's MIME type to color, kept by the caller so a refresh that reorders the types never repaints them. */
export type TypeColorsByPair = Map<number, Map<string, string>>;

function colorsFor(
  colorsByPair: TypeColorsByPair,
  ccPairId: number,
  keys: string[]
): string[] {
  const assigned = colorsByPair.get(ccPairId) ?? new Map<string, string>();
  colorsByPair.set(ccPairId, assigned);
  const taken = new Set<string>();
  for (const key of keys) {
    const kept = assigned.get(key);
    if (kept !== undefined) taken.add(kept);
  }
  return keys.map((key) => colorOf(assigned, taken, key));
}

/** The bar's segments and table rows: largest first, with every type past the eleventh in Other, last. */
export function documentTypeSlices(
  colorsByPair: TypeColorsByPair,
  ccPairId: number,
  types: DocumentTypeCount[]
): DocumentTypeSlice[] {
  const sorted = [...types].sort(
    (x, y) => y.count - x.count || x.mime_type.localeCompare(y.mime_type)
  );
  const shown = sorted.slice(0, TYPE_COLORS.length);
  const rest = sorted.slice(TYPE_COLORS.length);
  const colors = colorsFor(
    colorsByPair,
    ccPairId,
    shown.map((type) => type.mime_type)
  );
  const slices: DocumentTypeSlice[] = shown.map((type, index) => ({
    key: type.mime_type,
    count: type.count,
    sizeBytes: fullSize(type),
    colorClass: colors[index] ?? OTHER_COLOR,
  }));
  if (rest.length === 0) return slices;
  return [
    ...slices,
    {
      key: OTHER_DOCUMENT_TYPE,
      count: rest.reduce((sum, type) => sum + type.count, 0),
      sizeBytes: totalSize(rest),
      colorClass: OTHER_COLOR,
    },
  ];
}
