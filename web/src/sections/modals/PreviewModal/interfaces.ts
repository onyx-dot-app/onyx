import React from "react";
import type { ModalContentProps } from "@opal/components";

export interface PreviewContext {
  fileContent: string;
  fileUrl: string;
  fileName: string;
  language: string;
  lineCount: number;
  fileSize: string;
  zoom: number;
  onZoomIn: () => void;
  onZoomOut: () => void;
}

export interface PreviewVariant extends Required<
  Pick<ModalContentProps, "width" | "height">
> {
  /** Return true if this variant should handle the given file. */
  matches: (semanticIdentifier: string | null, mimeType: string) => boolean;
  /** Whether the fetcher should read the blob as text. */
  needsTextContent: boolean;
  /** Whether the fetcher should fetch backend-parsed content
   * (`?parsed=true`, JSON) into fileContent instead of the raw blob text.
   * Used for binary spreadsheet files. */
  needsParsedContent?: boolean;
  /** Whether the variant renders on a code-style background (bg-background-code-01). */
  codeBackground: boolean;
  /** String shown below the title in the modal header. */
  headerDescription: (ctx: PreviewContext) => string;
  /** Body content. */
  renderContent: (ctx: PreviewContext) => React.ReactNode;
  /** Left side of the floating footer (e.g. line count text, zoom controls). Return null for nothing. */
  renderFooterLeft: (ctx: PreviewContext) => React.ReactNode;
  /** Right side of the floating footer (e.g. copy + download buttons). */
  renderFooterRight: (ctx: PreviewContext) => React.ReactNode;
}
