// Pure selectors over processed citation state: split the turn's documents into the Sources-sheet
// sections and derive host/favicon strings. No React.

import { SearchDoc } from "@/chat/contracts/documents";
import { ProcessedMessageState } from "@/chat/messageProcessor";

export interface SelectedSources {
  cited: SearchDoc[]; // referenced by the answer, in citation order (non-file)
  more: SearchDoc[]; // found but not cited (non-file)
  files: SearchDoc[]; // user-uploaded files
  iconDocs: SearchDoc[]; // up to 3 for the Sources button icon stack
  count: number; // total sources listed in the sheet
  hasSources: boolean;
}

const HOST_RE = /^https?:\/\/([^/?#]+)/i;

export function domainOf(link: string | null): string | null {
  if (!link) return null;
  const match = HOST_RE.exec(link);
  if (!match) return null;
  return match[1].replace(/^www\./i, "");
}

// Public favicon service — the URL isn't auth'd, so a plain (non-bearer) image fetch is fine.
export function faviconUrl(link: string | null): string | null {
  const host = domainOf(link);
  if (!host) return null;
  return `https://www.google.com/s2/favicons?sz=64&domain=${host}`;
}

function isFileDoc(doc: SearchDoc): boolean {
  return doc.file_id != null;
}

export function selectSources(state: ProcessedMessageState): SelectedSources {
  const all = Array.from(state.documentMap.values());
  const files = all.filter(isFileDoc);
  const fileIds = new Set(files.map((doc) => doc.document_id));
  const citedIds = new Set(state.citations.map((c) => c.document_id));

  // Cited (non-file) docs, in the order they were first cited.
  const cited: SearchDoc[] = [];
  for (const citation of state.citations) {
    const doc = state.documentMap.get(citation.document_id);
    if (doc && !fileIds.has(doc.document_id)) cited.push(doc);
  }
  const more = all.filter(
    (doc) => !isFileDoc(doc) && !citedIds.has(doc.document_id),
  );

  // Fall through cited -> more -> files so a file-only answer still shows a (file) glyph in the bar.
  const iconDocs = (cited.length ? cited : more.length ? more : files).slice(
    0,
    3,
  );
  const count = cited.length + more.length + files.length;
  // From count, not raw citations/docs: citations whose documents never arrived must not render an
  // empty "Sources · 0".
  const hasSources = count > 0;

  return { cited, more, files, iconDocs, count, hasSources };
}
