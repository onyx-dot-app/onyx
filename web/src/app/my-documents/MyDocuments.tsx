"use client";

import { useCallback, useEffect, useState } from "react";
import { useDocuments } from "./useDocuments";
import { useRouter, useSearchParams } from "next/navigation";

import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { usePopup } from "@/components/admin/connectors/Popup";
import { FolderActions } from "./FolderActions";
import { FolderBreadcrumb } from "./FolderBreadcrumb";
import { FolderContents } from "./FolderContents";
import TextView from "@/components/chat_search/TextView";
import { Button } from "@/components/ui/button";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";

interface FolderResponse {
  children: { name: string; id: number }[];
  files: { name: string; document_id: string; id: number }[];
  parents: { name: string; id: number }[];
  name: string;
  id: number;
  document_id: string;
}

interface FolderTreeNode {
  id: number;
  name: string;
  parent_id: number | null;
  children?: FolderTreeNode[];
}

function buildTree(
  folders: { id: number; name: string; parent_id: number | null }[]
): FolderTreeNode[] {
  const map: { [key: number]: FolderTreeNode } = {};
  folders.forEach((f) => {
    map[f.id] = { ...f, children: [] };
  });
  const roots: FolderTreeNode[] = [];
  folders.forEach((f) => {
    if (f.parent_id === null) {
      roots.push(map[f.id]);
    } else {
      map[f.parent_id].children?.push(map[f.id]);
    }
  });
  return roots;
}

export default function MyDocuments() {
  const { documents, isLoading, error, loadDocuments, handleDeleteDocument } =
    useDocuments();
  const [selectedDocumentId, setSelectedDocumentId] = useState<number | null>(
    null
  );
  const [currentFolder, setCurrentFolder] = useState<number>(-1);
  const [folderContents, setFolderContents] = useState<FolderResponse | null>(
    null
  );
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<FolderResponse | null>(
    null
  );
  const [sortBy, setSortBy] = useState<"name" | "date">("name");
  const [page, setPage] = useState<number>(1);
  const [pageLimit] = useState<number>(20);
  const searchParams = useSearchParams();
  const router = useRouter();
  const { popup, setPopup } = usePopup();

  const [presentingDocument, setPresentingDocument] =
    useState<MinimalOnyxDocument | null>(null);
  const [isFilePickerOpen, setIsFilePickerOpen] = useState(false);
  const [folderTree, setFolderTree] = useState<FolderTreeNode[]>([]);

  const folderIdFromParams = parseInt(searchParams.get("path") || "-1", 10);

  const fetchFolderContents = useCallback(
    async (folderId: number, query?: string) => {
      if (query && query.trim().length > 0) {
        // Searching
        const res = await fetch(
          `/api/user/search?query=${encodeURIComponent(query)}`
        );
        const data = await res.json();
        // Mocking a folder response for search:
        const response: FolderResponse = {
          name: "Search Results",
          id: -999,
          document_id: "",
          children: data.folders.map((f: any) => ({ name: f.name, id: f.id })),
          files: data.files.map((fi: any) => ({
            name: fi.name,
            id: fi.id,
            document_id: fi.document_id,
          })),
          parents: [],
        };
        setSearchResults(response);
        setFolderContents(null);
        return;
      }

      try {
        const response = await fetch(
          `/api/user/folder/${folderId}?page=${page}&limit=${pageLimit}&sort=${sortBy}`
        );
        if (!response.ok) {
          throw new Error("Failed to fetch folder contents");
        }
        const data = await response.json();
        setFolderContents(data);
        setSearchResults(null);
      } catch (error) {
        console.error("Error fetching folder contents:", error);
        setPopup({
          message: "Failed to fetch folder contents",
          type: "error",
        });
      }
    },
    []
  );

  useEffect(() => {
    setCurrentFolder(folderIdFromParams);
    fetchFolderContents(folderIdFromParams, searchQuery);
  }, []);

  const refreshFolderContents = useCallback(() => {
    // fetchFolderContents(currentFolder, searchQuery);
  }, [fetchFolderContents, currentFolder, searchQuery]);

  useEffect(() => {
    const loadFileSystem = async () => {
      const res = await fetch("/api/user/file-system");
      const data = await res.json();
      const folders = data.folders.map((f: any) => ({
        id: f.id,
        name: f.name,
        parent_id: f.parent_id,
      }));
      const tree = buildTree(folders);
      setFolderTree(tree);
    };
    loadFileSystem();
  }, []);

  const handleFolderClick = (id: number) => {
    router.push(`/my-documents?path=${id}`);
    setPage(1);
    // refreshFolderContents();
  };

  const handleBreadcrumbClick = (folderId: number) => {
    router.push(`/my-documents?path=${folderId}`);
    setPage(1);
    // refreshFolderContents();
  };

  const handleCreateFolder = async (folderName: string) => {
    try {
      const response = await fetch("/api/user/folder", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: folderName, parent_id: currentFolder }),
      });
      if (response.ok) {
        refreshFolderContents();
        setPopup({
          message: "Folder created successfully",
          type: "success",
        });
      } else {
        throw new Error("Failed to create folder");
      }
    } catch (error) {
      console.error("Error creating folder:", error);
      setPopup({
        message: "Failed to create folder",
        type: "error",
      });
    }
  };

  const handleDeleteItem = async (itemId: number, isFolder: boolean) => {
    try {
      const endpoint = isFolder
        ? `/api/user/folder/${itemId}`
        : `/api/user/file/${itemId}`;
      const response = await fetch(endpoint, {
        method: "DELETE",
      });
      if (response.ok) {
        fetchFolderContents(currentFolder, searchQuery);
        setPopup({
          message: `${isFolder ? "Folder" : "File"} deleted successfully`,
          type: "success",
        });
      } else {
        throw new Error(`Failed to delete ${isFolder ? "folder" : "file"}`);
      }
    } catch (error) {
      console.error("Error deleting item:", error);
      setPopup({
        message: `Failed to delete ${isFolder ? "folder" : "file"}`,
        type: "error",
      });
    }
    refreshFolderContents();
  };

  const handleUploadFiles = async (files: FileList) => {
    const formData = new FormData();
    for (let i = 0; i < files.length; i++) {
      formData.append("files", files[i]);
    }
    formData.append(
      "folder_id",
      currentFolder.toString() === "-1" ? "" : currentFolder.toString()
    );

    try {
      const response = await fetch("/api/user/file/upload", {
        method: "POST",
        body: formData,
      });
      if (response.ok) {
        fetchFolderContents(currentFolder, searchQuery);
        setPopup({
          message: "Files uploaded successfully",
          type: "success",
        });
      } else {
        throw new Error("Failed to upload files");
      }
    } catch (error) {
      console.error("Error uploading files:", error);
      setPopup({
        message: "Failed to upload files",
        type: "error",
      });
    }
    refreshFolderContents();
  };

  const handleMoveItem = async (
    itemId: number,
    destinationFolderId: number,
    isFolder: boolean
  ) => {
    // @router.put("/user/folder/{folder_id}/move")
    // def move_folder(
    //     folder_id: int,
    //     new_parent_id: int | None,
    //     user: User = Depends(current_user),
    //     db_session: Session = Depends(get_session),
    // ) -> FolderResponse:
    //     user_id = us

    // @router.put("/user/file/{file_id}/move")
    // def move_file(
    //     file_id: int,
    //     new_folder_id: int | None,
    //     user: User = Depends(current_user),
    //     db_session: Session

    console.log("Moving item:", itemId, "to folder:", destinationFolderId);
    console.log("isFolder:", isFolder);
    // i;
    const endpoint = isFolder
      ? `/api/user/folder/${itemId}/move`
      : `/api/user/file/${itemId}/move`;
    try {
      const response = await fetch(endpoint, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          new_parent_id: destinationFolderId,
          [isFolder ? "folder_id" : "file_id"]: itemId,
        }),
      });
      if (response.ok) {
        fetchFolderContents(currentFolder, searchQuery);
        setPopup({
          message: `${isFolder ? "Folder" : "File"} moved successfully`,
          type: "success",
        });
      } else {
        throw new Error("Failed to move item");
      }
    } catch (error) {
      console.error("Error moving item:", error);
      setPopup({
        message: "Failed to move item",
        type: "error",
      });
    }
    refreshFolderContents();
  };

  const handleDownloadItem = async (documentId: string) => {
    try {
      const response = await fetch(
        `/api/chat/file/${encodeURIComponent(documentId)}`,
        {
          method: "GET",
        }
      );
      if (!response.ok) {
        throw new Error("Failed to fetch file");
      }
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const contentDisposition = response.headers.get("Content-Disposition");
      const fileName = contentDisposition
        ? contentDisposition.split("filename=")[1]
        : "document";

      const link = document.createElement("a");
      link.href = url;
      link.download = fileName || "document";
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);

      window.URL.revokeObjectURL(url);
    } catch (error) {
      console.error("Error downloading file:", error);
      setPopup({
        message: "Failed to download file",
        type: "error",
      });
    }
  };

  const handleSaveContext = (selectedItems: string[]) => {
    console.log("Saving context for:", selectedItems);
    // Implement logic if needed
  };

  const handleDeleteSelected = (selectedItems: string[]) => {
    console.log("Deleting:", selectedItems);
    // Implement logic if needed
  };

  const onRenameItem = async (
    itemId: number,
    newName: string,
    isFolder: boolean
  ) => {
    const endpoint = isFolder
      ? `/api/user/folder/${itemId}?name=${encodeURIComponent(newName)}`
      : `/api/user/file/${itemId}/rename?name=${encodeURIComponent(newName)}`;
    try {
      const response = await fetch(endpoint, {
        method: "PUT",
      });
      if (response.ok) {
        fetchFolderContents(currentFolder, searchQuery);
        setPopup({
          message: `${isFolder ? "Folder" : "File"} renamed successfully`,
          type: "success",
        });
      } else {
        throw new Error("Failed to rename item");
      }
    } catch (error) {
      console.error("Error renaming item:", error);
      setPopup({
        message: `Failed to rename ${isFolder ? "folder" : "file"}`,
        type: "error",
      });
    }
  };

  const handleDelete = async () => {
    if (selectedDocumentId !== null) {
      await handleDeleteDocument(selectedDocumentId);
      setSelectedDocumentId(null);
    }
  };

  const handleRefresh = () => {
    loadDocuments();
  };

  return (
    <div className="container mx-auto p-4">
      {presentingDocument && (
        <TextView
          presentingDocument={presentingDocument}
          onClose={() => setPresentingDocument(null)}
        />
      )}
      {popup}
      <div className="flex-grow">
        <div className="flex items-center mb-2 space-x-2">
          {/* <Input
              type="text"
              placeholder="Search..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="max-w-xs"
            />
            <Button
              onClick={() => fetchFolderContents(currentFolder, searchQuery)}
            >
              Search
            </Button> */}
          <div className="flex items-center space-x-2 ml-auto">
            <select
              className="border border-gray-300 rounded p-1 text-sm"
              value={sortBy}
              onChange={(e) => {
                setSortBy(e.target.value as "name" | "date");
                fetchFolderContents(currentFolder, searchQuery);
              }}
            >
              <option value="name">Sort by Name</option>
              <option value="date">Sort by Date</option>
            </select>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setPage((prev) => Math.max(prev - 1, 1));
                fetchFolderContents(currentFolder, searchQuery);
              }}
            >
              Prev
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setPage((prev) => prev + 1);
                fetchFolderContents(currentFolder, searchQuery);
              }}
            >
              Next
            </Button>
          </div>
        </div>

        <FolderBreadcrumb
          currentFolder={{
            name: searchResults
              ? "Search Results"
              : folderContents
                ? folderContents.name
                : "",
            id: searchResults ? -999 : currentFolder,
          }}
          parents={searchResults ? [] : folderContents?.parents || []}
          onBreadcrumbClick={handleBreadcrumbClick}
        />
        <Card>
          <CardHeader>
            <CardTitle>
              {searchResults ? "Search Results" : "Folder Contents"}
            </CardTitle>
            <FolderActions
              onRefresh={() => fetchFolderContents(currentFolder, searchQuery)}
              onCreateFolder={handleCreateFolder}
              onUploadFiles={handleUploadFiles}
            />
          </CardHeader>
          <CardContent>
            {searchResults ? (
              <FolderContents
                setPresentingDocument={(
                  document_id: string,
                  semantic_identifier: string
                ) =>
                  setPresentingDocument({ document_id, semantic_identifier })
                }
                contents={searchResults}
                onFolderClick={handleFolderClick}
                currentFolder={currentFolder}
                onDeleteItem={handleDeleteItem}
                onDownloadItem={handleDownloadItem}
                onMoveItem={handleMoveItem}
                onRenameItem={onRenameItem}
              />
            ) : folderContents ? (
              <FolderContents
                setPresentingDocument={(
                  document_id: string,
                  semantic_identifier: string
                ) =>
                  setPresentingDocument({ document_id, semantic_identifier })
                }
                contents={folderContents}
                onFolderClick={handleFolderClick}
                currentFolder={currentFolder}
                onDeleteItem={handleDeleteItem}
                onDownloadItem={handleDownloadItem}
                onMoveItem={handleMoveItem}
                onRenameItem={onRenameItem}
              />
            ) : (
              <p>Loading...</p>
            )}
          </CardContent>
        </Card>
      </div>

      {error && <div className="text-error">{error}</div>}

      {isLoading ? (
        <div>Loading documents...</div>
      ) : (
        <ul>
          {documents.map((doc) => (
            <li key={doc.id}>
              {doc.document_id}
              <button onClick={() => handleDeleteDocument(doc.id)}>
                Delete
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
