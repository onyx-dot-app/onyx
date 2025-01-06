"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { usePopup } from "@/components/admin/connectors/Popup";
import { FolderActions } from "./FolderActions";
import { FolderBreadcrumb } from "./FolderBreadcrumb";
import { FolderContents } from "./FolderContents";
import TextView from "@/components/chat_search/TextView";
import { Button } from "@/components/ui/button";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";
import { PageSelector } from "@/components/PageSelector";

interface FolderResponse {
  children: { name: string; id: number }[];
  files: { name: string; document_id: string; id: number }[];
  parents: { name: string; id: number }[];
  name: string;
  id: number;
  document_id: string;
}

export default function MyDocuments() {
  const [currentFolder, setCurrentFolder] = useState<number>(-1);
  const [folderContents, setFolderContents] = useState<FolderResponse | null>(
    null
  );

  const [page, setPage] = useState<number>(1);

  const pageLimit = 10;
  const searchParams = useSearchParams();
  const router = useRouter();
  const { popup, setPopup } = usePopup();

  const [presentingDocument, setPresentingDocument] =
    useState<MinimalOnyxDocument | null>(null);

  const folderIdFromParams = parseInt(searchParams.get("path") || "-1", 10);

  const fetchFolderContents = useCallback(async (folderId: number) => {
    try {
      const response = await fetch(`/api/user/folder/${folderId}?page=${page}`);
      if (!response.ok) {
        throw new Error("Failed to fetch folder contents");
      }
      const data = await response.json();
      setFolderContents(data);
    } catch (error) {
      console.error("Error fetching folder contents:", error);
      setPopup({
        message: "Failed to fetch folder contents",
        type: "error",
      });
    }
  }, []);

  useEffect(() => {
    setCurrentFolder(folderIdFromParams);
    fetchFolderContents(folderIdFromParams);
  }, [searchParams]);

  const refreshFolderContents = useCallback(() => {
    fetchFolderContents(currentFolder);
  }, [fetchFolderContents, currentFolder]);

  const handleFolderClick = (id: number) => {
    router.push(`/my-documents?path=${id}`);
    setPage(1);
  };

  const handleBreadcrumbClick = (folderId: number) => {
    router.push(`/my-documents?path=${folderId}`);
    setPage(1);
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
        fetchFolderContents(currentFolder);
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
        await fetchFolderContents(currentFolder);
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

    await refreshFolderContents();
    setPage(1);
  };

  const handleMoveItem = async (
    itemId: number,
    destinationFolderId: number | null,
    isFolder: boolean
  ) => {
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
        fetchFolderContents(currentFolder);
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
        fetchFolderContents(currentFolder);
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
        <FolderBreadcrumb
          currentFolder={{
            name: folderContents ? folderContents.name : "",
            id: currentFolder,
          }}
          parents={folderContents?.parents || []}
          onBreadcrumbClick={handleBreadcrumbClick}
        />
        <Card>
          <CardHeader>
            <CardTitle>Folder Contents</CardTitle>
            <FolderActions
              onRefresh={() => fetchFolderContents(currentFolder)}
              onCreateFolder={handleCreateFolder}
              onUploadFiles={handleUploadFiles}
            />
          </CardHeader>
          <CardContent>
            {folderContents ? (
              folderContents.files.length > 0 ||
              folderContents.children.length > 0 ? (
                <FolderContents
                  currentPage={page}
                  pageLimit={pageLimit}
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
                <p>No content in this folder</p>
              )
            ) : (
              <p>Loading...</p>
            )}
          </CardContent>
        </Card>
        <div className="mt-3 flex">
          <div className="mx-auto">
            <PageSelector
              currentPage={page}
              totalPages={Math.ceil(
                ((folderContents?.files?.length || 0) +
                  (folderContents?.children?.length || 0)) /
                  pageLimit
              )}
              onPageChange={(newPage) => {
                setPage(newPage);
                window.scrollTo({
                  top: 0,
                  left: 0,
                  behavior: "smooth",
                });
              }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
