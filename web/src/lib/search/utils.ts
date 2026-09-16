import { ValidSources } from "@/lib/types";
import { MinimalOnyxDocument, OnyxDocument } from "@/lib/search/interfaces";
import { transformLinkUri } from "@/lib/utils";

export const openExternalLink = (url: string) => {
  const safeUrl = transformLinkUri(url);
  if (safeUrl) {
    window.open(safeUrl, "_blank", "noopener,noreferrer");
  }
};

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
