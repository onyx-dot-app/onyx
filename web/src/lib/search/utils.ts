import { ValidSources } from "@/lib/types";
import { MinimalOnyxDocument, OnyxDocument } from "@/lib/search/types";
import { transformLinkUri } from "@/lib/utils";

export const openExternalLink = (url: string) => {
  const safeUrl = transformLinkUri(url);
  if (safeUrl) {
    window.open(safeUrl, "_blank", "noopener,noreferrer");
  }
};

export function getDocumentSourceTypes(
  document: Pick<OnyxDocument, "source_type" | "source_types">
): ValidSources[] {
  return document.source_types?.length
    ? [...new Set(document.source_types)]
    : [document.source_type];
}

export function documentMatchesAnySource(
  document: Pick<OnyxDocument, "source_type" | "source_types">,
  selectedSources: ValidSources[]
): boolean {
  return (
    selectedSources.length === 0 ||
    getDocumentSourceTypes(document).some((source) =>
      selectedSources.includes(source)
    )
  );
}

export function countDocumentsBySource(
  documents: Pick<OnyxDocument, "source_type" | "source_types">[]
): Map<ValidSources, number> {
  const counts = new Map<ValidSources, number>();
  for (const document of documents) {
    for (const source of getDocumentSourceTypes(document)) {
      counts.set(source, (counts.get(source) ?? 0) + 1);
    }
  }
  return counts;
}

// If we have a link, open it in a new tab (including if it's a file)
// If above fails and we have a file, update the presenting document
export const openDocument = (
  document: OnyxDocument,
  updatePresentingDocument?: (document: MinimalOnyxDocument) => void
) => {
  if (document.link) {
    openExternalLink(document.link);
  } else if (
    document.source_type === ValidSources.File ||
    document.source_type === ValidSources.UserFile
  ) {
    updatePresentingDocument?.(document);
  }
};
