// Mirrors web sourceTagUtils.ts. Deviation: mobile lacks the full per-connector
// source-metadata map, so getDisplayNameForSource humanizes the source_type for
// internal docs instead of looking up a curated connector name.

import type { OnyxDocument } from "@/lib/types";

export interface SourceInfo {
  id: string;
  title: string;
  sourceType: string;
  sourceUrl?: string;
  description?: string;
  date?: string | null;
  isInternet: boolean;
}

const MAX_TITLE_LENGTH = 40;

export function truncateText(text: string, maxLength = MAX_TITLE_LENGTH): string {
  if (text.length <= maxLength) return text;
  return text.slice(0, Math.max(0, maxLength - 1)).trimEnd() + "…";
}

// "google_drive" -> "Google Drive".
export function humanizeSourceType(sourceType: string): string {
  if (!sourceType) return "Source";
  return sourceType
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

export function documentToSourceInfo(doc: OnyxDocument): SourceInfo {
  return {
    id: doc.document_id,
    title: doc.semantic_identifier || "Unknown",
    sourceType: doc.source_type,
    sourceUrl: doc.link || undefined,
    description: doc.blurb,
    date: doc.updated_at,
    isInternet: doc.is_internet || doc.source_type === "web",
  };
}

// Pill/chip label: web results -> page title; internal docs -> humanized
// connector name (approximates web's getSourceDisplayName).
export function getDisplayNameForSource(doc: OnyxDocument): string {
  const isWeb = doc.source_type === "web" || doc.is_internet;
  if (isWeb) {
    return truncateText(doc.semantic_identifier || "Web", MAX_TITLE_LENGTH);
  }
  return truncateText(
    humanizeSourceType(doc.source_type) ||
      doc.semantic_identifier ||
      "Source",
    MAX_TITLE_LENGTH
  );
}
