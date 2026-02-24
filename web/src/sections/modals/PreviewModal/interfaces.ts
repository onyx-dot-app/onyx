import React from "react";
import { ModalContentProps } from "@/refresh-components/Modal";

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

export interface PreviewVariant
  extends Required<Pick<ModalContentProps, "width" | "height">> {
  /** Return true if this variant should handle the given file. */
  matches: (semanticIdentifier: string | null, mimeType: string) => boolean;
  /** Whether the fetcher should read the blob as text. */
  needsTextContent: boolean;
  /** String shown below the title in the modal header. */
  headerDescription: (ctx: PreviewContext) => string;
  /** Body content. */
  renderContent: (ctx: PreviewContext) => React.ReactNode;
  /** Left side of the floating footer (e.g. line count text, zoom controls). Return null for nothing. */
  renderFooterLeft: (ctx: PreviewContext) => React.ReactNode;
  /** Right side of the floating footer (e.g. copy + download buttons). */
  renderFooterRight: (ctx: PreviewContext) => React.ReactNode;
}
