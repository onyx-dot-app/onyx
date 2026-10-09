import type { ReactNode } from "react";
import { findTermRanges } from "@/lib/documentSets/search";

interface HighlightedTextProps {
  text: string;
  terms: string[];
}

/** Renders `text` with each occurrence of a search term marked. */
export default function HighlightedText({ text, terms }: HighlightedTextProps) {
  const ranges = findTermRanges(text, terms);
  if (ranges.length === 0) return text;

  const parts: ReactNode[] = [];
  let cursor = 0;
  for (const [start, end] of ranges) {
    if (start > cursor) parts.push(text.slice(cursor, start));
    parts.push(
      <mark key={start} className="bg-highlight-match text-inherit rounded-04">
        {text.slice(start, end)}
      </mark>
    );
    cursor = end;
  }
  if (cursor < text.length) parts.push(text.slice(cursor));
  return parts;
}
