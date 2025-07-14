import { useState, useRef, useCallback, useMemo } from "react";
import { OnyxDocument } from "@/lib/search/interfaces";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";

export interface UseDocumentManagementProps {
  maxTokens: number;
}

export function useDocumentManagement({
  maxTokens,
}: UseDocumentManagementProps) {
  // UI STATE: Document viewer modal - currently displayed document for reading
  const [presentingDocument, setPresentingDocument] =
    useState<MinimalOnyxDocument | null>(null);

  // UI STATE: Selected documents for context (displayed in document sidebar)
  const [selectedDocuments, setSelectedDocuments] = useState<OnyxDocument[]>(
    []
  );
  // UI STATE: Token count for selected documents (for context limit management)
  const [selectedDocumentTokens, setSelectedDocumentTokens] = useState(0);

  // UI REF: Master flexbox container for responsive layout calculations
  const masterFlexboxRef = useRef<HTMLDivElement>(null);
  // UI STATE: Document sidebar maximum width (responsive layout constraint)
  const [maxDocumentSidebarWidth, setMaxDocumentSidebarWidth] = useState<
    number | null
  >(null);

  // UI FUNCTION: Calculate responsive document sidebar width based on screen size
  const adjustDocumentSidebarWidth = useCallback(() => {
    if (masterFlexboxRef.current && document.documentElement.clientWidth) {
      // numbers below are based on the actual width the center section for different
      // screen sizes. `1700` corresponds to the custom "3xl" tailwind breakpoint
      // NOTE: some buffer is needed to account for scroll bars
      if (document.documentElement.clientWidth > 1700) {
        setMaxDocumentSidebarWidth(masterFlexboxRef.current.clientWidth - 950);
      } else if (document.documentElement.clientWidth > 1420) {
        setMaxDocumentSidebarWidth(masterFlexboxRef.current.clientWidth - 760);
      } else {
        setMaxDocumentSidebarWidth(masterFlexboxRef.current.clientWidth - 660);
      }
    }
  }, []);

  // UI FUNCTION: Clear selected documents and reset token count
  const clearSelectedDocuments = useCallback(() => {
    setSelectedDocuments([]);
    setSelectedDocumentTokens(0);
  }, []);

  // UI FUNCTION: Toggle document selection in document sidebar
  const toggleDocumentSelection = useCallback((document: OnyxDocument) => {
    setSelectedDocuments((prev) =>
      prev.some((d) => d.document_id === document.document_id)
        ? prev.filter((d) => d.document_id !== document.document_id)
        : [...prev, document]
    );
  }, []);

  return {
    presentingDocument,
    setPresentingDocument,
    selectedDocuments,
    setSelectedDocuments,
    selectedDocumentTokens,
    setSelectedDocumentTokens,
    masterFlexboxRef,
    maxDocumentSidebarWidth,
    adjustDocumentSidebarWidth,
    clearSelectedDocuments,
    toggleDocumentSelection,
  };
}
