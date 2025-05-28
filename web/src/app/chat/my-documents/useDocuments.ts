import { useState, useEffect, useCallback } from "react";

// API functions
const fetchDocuments = async (): Promise<Document[]> => {
  const response = await fetch("/api/manage/admin/documents");
  if (!response.ok) {
    throw new Error("Failed to fetch documents");
  }
  return response.json();
};

const deleteDocument = async (documentId: number): Promise<void> => {
  const response = await fetch(`/api/manage/admin/documents/${documentId}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    throw new Error("Failed to delete document");
  }
};

export interface Document {
  id: number;
  document_id: string;
}
// Custom hook
export const useDocuments = () => {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadDocuments = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const fetchedDocuments = await fetchDocuments();
      setDocuments(fetchedDocuments);
    } catch (err) {
      setError("Failed to load documents err: " + err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const handleDeleteDocument = async (documentId: number) => {
    try {
      await deleteDocument(documentId);
      await loadDocuments();
    } catch (err) {
      setError("Failed to delete document");
    }
  };

  useEffect(() => {
    loadDocuments();
  }, [loadDocuments]);

  return {
    documents,
    isLoading,
    error,
    loadDocuments,
    handleDeleteDocument,
  };
};
