import { OnyxDocument } from "@/lib/search/interfaces";
import { useState } from "react";
import { FileResponse } from "./my-documents/DocumentsContext";

interface DocumentInfo {
  num_chunks: number;
  num_tokens: number;
}

async function fetchDocumentLength(documentId: string) {
  const response = await fetch(
    `/api/document/document-size-info?document_id=${documentId}`
  );
  if (!response.ok) {
    return 0;
  }
  const data = (await response.json()) as DocumentInfo;
  return data.num_tokens;
}

export function useDocumentSelection(): [
  FileResponse[],
  (file: FileResponse) => void,
  (file: FileResponse) => void,
  OnyxDocument[],
  (document: OnyxDocument) => void,
  () => void,
  number,
] {
  const [selectedFiles, setSelectedFiles] = useState<FileResponse[]>([]);
  const [selectedDocuments, setSelectedDocuments] = useState<OnyxDocument[]>(
    []
  );
  const removeSelectedFile = (file: FileResponse) => {
    setSelectedFiles(selectedFiles.filter((f) => f.id !== file.id));
  };

  const addSelectedFile = (file: FileResponse) => {
    // Check if file already exists in the array to avoid duplicates
    setSelectedFiles((files) => {
      // Check if file already exists in the array to avoid duplicates
      if (files.some((f) => f.id === file.id)) {
        return files;
      }
      return [...files, file];
    });
  };
  const [totalTokens, setTotalTokens] = useState(0);
  const selectedDocumentIds = selectedDocuments.map(
    (document) => document.document_id
  );
  const documentIdToLength = new Map<string, number>();

  function toggleDocumentSelection(document: OnyxDocument) {
    const documentId = document.document_id;
    const isAdding = !selectedDocumentIds.includes(documentId);
    if (!isAdding) {
      setSelectedDocuments(
        selectedDocuments.filter(
          (document) => document.document_id !== documentId
        )
      );
    } else {
      setSelectedDocuments([...selectedDocuments, document]);
    }
    if (documentIdToLength.has(documentId)) {
      const length = documentIdToLength.get(documentId)!;
      setTotalTokens(isAdding ? totalTokens + length : totalTokens - length);
    } else {
      fetchDocumentLength(documentId).then((length) => {
        documentIdToLength.set(documentId, length);
        setTotalTokens(isAdding ? totalTokens + length : totalTokens - length);
      });
    }
  }

  function clearDocuments() {
    setSelectedDocuments([]);
    setTotalTokens(0);
  }

  return [
    selectedFiles,
    addSelectedFile,
    removeSelectedFile,
    selectedDocuments,
    toggleDocumentSelection,
    clearDocuments,
    totalTokens,
  ];
}
