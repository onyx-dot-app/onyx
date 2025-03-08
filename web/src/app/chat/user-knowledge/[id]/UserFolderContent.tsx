import React, { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ChevronRight, MessageSquare } from "lucide-react";
import { useDocumentsContext } from "../DocumentsContext";
import { useChatContext } from "@/components/context/ChatContext";
import { Button } from "@/components/ui/button";
import { DocumentList } from "./components/DocumentList";
import { usePopup } from "@/components/admin/connectors/Popup";
import { usePopupFromQuery } from "@/components/popup/PopupFromQuery";
import { Input } from "@/components/ui/input";
import { DeleteEntityModal } from "@/components/DeleteEntityModal";
import { MoveFolderModal } from "@/components/MoveFolderModal";
import { FolderResponse } from "../DocumentsContext";
import { getDisplayNameForModel } from "@/lib/hooks";

export default function UserFolderContent({ folderId }: { folderId: number }) {
  const router = useRouter();
  const { llmProviders } = useChatContext();
  const { popup, setPopup } = usePopup();
  const {
    folderDetails,
    getFolderDetails,
    downloadItem,
    renameItem,
    deleteItem,
    createFileFromLink,
    handleUpload,
    refreshFolderDetails,
    getFolders,
    moveItem,
    updateFolderDetails,
  } = useDocumentsContext();

  const [isCapacityOpen, setIsCapacityOpen] = useState(false);
  const [isSharedOpen, setIsSharedOpen] = useState(false);
  const [editingItemId, setEditingItemId] = useState<number | null>(null);
  const [newItemName, setNewItemName] = useState("");
  const [editingDescription, setEditingDescription] = useState(false);
  const [newDescription, setNewDescription] = useState("");
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const [deleteItemId, setDeleteItemId] = useState<number | null>(null);
  const [deleteItemType, setDeleteItemType] = useState<"file" | "folder">(
    "file"
  );
  const [deleteItemName, setDeleteItemName] = useState("");
  const [isMoveModalOpen, setIsMoveModalOpen] = useState(false);
  const [folders, setFolders] = useState<FolderResponse[]>([]);

  const modelDescriptors = llmProviders.flatMap((provider) =>
    Object.entries(provider.model_token_limits ?? {}).map(
      ([modelName, maxTokens]) => ({
        modelName,
        provider: provider.provider,
        maxTokens,
      })
    )
  );

  const [selectedModel, setSelectedModel] = useState(modelDescriptors[0]);

  const { popup: folderCreatedPopup } = usePopupFromQuery({
    "folder-created": {
      message: `Folder created successfully`,
      type: "success",
    },
  });

  useEffect(() => {
    if (!folderDetails) {
      getFolderDetails(folderId);
    }
  }, [folderId, folderDetails, getFolderDetails]);

  useEffect(() => {
    const fetchFolders = async () => {
      try {
        const fetchedFolders = await getFolders();
        setFolders(fetchedFolders);
      } catch (error) {
        console.error("Error fetching folders:", error);
      }
    };

    fetchFolders();
  }, []);

  const handleBack = () => {
    router.push("/chat/user-knowledge");
  };
  if (!folderDetails) {
    return (
      <div className="min-h-full w-full min-w-0 flex-1 mx-auto max-w-5xl px-4 pb-20 md:pl-8 mt-6 md:pr-8 2xl:pr-14">
        <div className="text-left space-y-4">
          <h2 className="flex items-center gap-1.5 text-lg font-medium leading-tight tracking-tight max-md:hidden">
            No Folder Found
          </h2>
          <p className="text-neutral-600">
            The requested folder does not exist or you dont have permission to
            view it.
          </p>
          <Button onClick={handleBack} variant="outline" className="mt-2">
            Back to My Documents
          </Button>
        </div>
      </div>
    );
  }

  const totalTokens = folderDetails.files.reduce(
    (acc, file) => acc + (file.token_count || 0),
    0
  );
  const maxTokens = selectedModel.maxTokens;
  const tokenPercentage = (totalTokens / maxTokens) * 100;

  const handleStartChat = () => {
    router.push(`/chat?userFolderId=${folderId}`);
  };

  const handleCreateFileFromLink = async (url: string) => {
    await createFileFromLink(url, folderId);
  };

  const handleRenameItem = async (
    itemId: number,
    currentName: string,
    isFolder: boolean
  ) => {
    setEditingItemId(itemId);
    setNewItemName(currentName);
  };

  const handleSaveRename = async (itemId: number, isFolder: boolean) => {
    if (newItemName && newItemName !== folderDetails.name) {
      try {
        await renameItem(itemId, newItemName, isFolder);
        setPopup({
          message: `${isFolder ? "Folder" : "File"} renamed successfully`,
          type: "success",
        });
        await refreshFolderDetails();
      } catch (error) {
        console.error("Error renaming item:", error);
        setPopup({
          message: `Failed to rename ${isFolder ? "folder" : "file"}`,
          type: "error",
        });
      }
    }
    setEditingItemId(null);
  };

  const handleCancelRename = () => {
    setEditingItemId(null);
    setNewItemName("");
  };

  // const handleEditDescription = () => {
  //   if (folderDetails) {
  //     setEditingDescription(true);
  //     setNewDescription(folderDetails.description);
  //   }
  // };

  const handleSaveDescription = async () => {
    if (folderDetails && newDescription !== folderDetails.description) {
      try {
        alert(
          JSON.stringify({
            id: folderDetails.id,
            name: folderDetails.name,
            newDescription,
          })
        );
        await updateFolderDetails(
          folderDetails.id,
          folderDetails.name,
          newDescription
        );
        setPopup({
          message: "Folder description updated successfully",
          type: "success",
        });
        await refreshFolderDetails();
      } catch (error) {
        console.error("Error updating folder description:", error);
        setPopup({
          message: "Failed to update folder description",
          type: "error",
        });
      }
    }
    setEditingDescription(false);
  };

  const handleCancelDescription = () => {
    setEditingDescription(false);
    setNewDescription("");
  };

  const handleDeleteItem = (
    itemId: number,
    isFolder: boolean,
    itemName: string
  ) => {
    setDeleteItemId(itemId);
    setDeleteItemType(isFolder ? "folder" : "file");
    setDeleteItemName(itemName);
    setIsDeleteModalOpen(true);
  };

  const confirmDelete = async () => {
    if (deleteItemId !== null) {
      try {
        await deleteItem(deleteItemId, deleteItemType === "folder");
        setPopup({
          message: `${deleteItemType} deleted successfully`,
          type: "success",
        });
        await refreshFolderDetails();
      } catch (error) {
        console.error("Error deleting item:", error);
        setPopup({
          message: `Failed to delete ${deleteItemType}`,
          type: "error",
        });
      }
    }
    setIsDeleteModalOpen(false);
  };

  const handleMoveFolder = () => {
    setIsMoveModalOpen(true);
  };

  const confirmMove = async (targetFolderId: number) => {
    try {
      await moveItem(folderId, targetFolderId, true);
      setPopup({
        message: "Folder moved successfully",
        type: "success",
      });
      router.push(`/chat/user-knowledge/${targetFolderId}`);
    } catch (error) {
      console.error("Error moving folder:", error);
      setPopup({
        message: "Failed to move folder",
        type: "error",
      });
    }
    setIsMoveModalOpen(false);
  };

  const handleMoveFile = async (fileId: number, targetFolderId: number) => {
    try {
      await moveItem(fileId, targetFolderId, false);
      setPopup({
        message: "File moved successfully",
        type: "success",
      });
      await refreshFolderDetails();
    } catch (error) {
      console.error("Error moving file:", error);
      setPopup({
        message: "Failed to move file",
        type: "error",
      });
    }
  };

  return (
    <div className="min-h-full w-full min-w-0 flex-1 mx-auto mt-6 w-full max-w-[90rem] flex-1 px-4 pb-20 md:pl-8 lg:mt-7 md:pr-8 2xl:pr-14 relative">
      {popup}
      {folderCreatedPopup}
      <DeleteEntityModal
        isOpen={isDeleteModalOpen}
        onClose={() => setIsDeleteModalOpen(false)}
        onConfirm={confirmDelete}
        entityType={deleteItemType}
        entityName={deleteItemName}
      />
      <MoveFolderModal
        isOpen={isMoveModalOpen}
        onClose={() => setIsMoveModalOpen(false)}
        onMove={confirmMove}
        folders={folders}
        currentFolderId={folderId}
      />

      <div className="flex flex-col w-full">
        <div className="flex items-center mb-4">
          <nav className="flex text-lg items-center">
            <span
              className="font-medium leading-tight tracking-tight text-lg text-neutral-800 dark:text-neutral-300 hover:text-neutral-900 dark:hover:text-neutral-100 cursor-pointer flex items-center text-base"
              onClick={handleBack}
            >
              My Documents
            </span>
            <span className="text-neutral-800 flex items-center">
              <ChevronRight className="h-4 w-4" />
            </span>
            {editingItemId === folderDetails.id ? (
              <div className="flex  -my-1 items-center">
                <Input
                  value={newItemName}
                  onChange={(e) => setNewItemName(e.target.value)}
                  className="mr-2 h-8"
                />
                <Button
                  onClick={() => handleSaveRename(folderDetails.id, true)}
                  className="mr-2 h-8 py-0"
                  size="sm"
                >
                  Save
                </Button>
                <Button
                  onClick={handleCancelRename}
                  variant="outline"
                  className="h-8 py-0"
                  size="sm"
                >
                  Cancel
                </Button>
              </div>
            ) : (
              <h1
                className="text-neutral-900 dark:text-neutral-100 font-medium cursor-pointer "
                onClick={() =>
                  handleRenameItem(folderDetails.id, folderDetails.name, true)
                }
              >
                {folderDetails.name}
              </h1>
            )}
          </nav>
        </div>

        {/* Search Bar */}
        <div className="mb-6">
          <div className="relative w-full max-w-md">
            <input
              type="text"
              placeholder="Search documents..."
              className="w-full px-4 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
            <div className="absolute inset-y-0 left-3 flex items-center pointer-events-none">
              <svg
                width="15"
                height="15"
                viewBox="0 0 15 15"
                fill="none"
                xmlns="http://www.w3.org/2000/svg"
                className="w-4 h-4 text-gray-400"
              >
                <path
                  d="M10 6.5C10 8.433 8.433 10 6.5 10C4.567 10 3 8.433 3 6.5C3 4.567 4.567 3 6.5 3C8.433 3 10 4.567 10 6.5ZM9.30884 10.0159C8.53901 10.6318 7.56251 11 6.5 11C4.01472 11 2 8.98528 2 6.5C2 4.01472 4.01472 2 6.5 2C8.98528 2 11 4.01472 11 6.5C11 7.56251 10.6318 8.53901 10.0159 9.30884L12.8536 12.1464C13.0488 12.3417 13.0488 12.6583 12.8536 12.8536C12.6583 13.0488 12.3417 13.0488 12.1464 12.8536L9.30884 10.0159Z"
                  fill="currentColor"
                  fillRule="evenodd"
                  clipRule="evenodd"
                ></path>
              </svg>
            </div>
          </div>
        </div>

        {/* Status Bar & Chat Button */}
        <div className="flex justify-between items-center mb-6">
          <div className="flex items-center space-x-2">
            <Button
              onClick={handleStartChat}
              className="flex items-center gap-2 bg-black text-white hover:bg-gray-800"
            >
              <MessageSquare className="w-4 h-4" />
              Chat with this folder
            </Button>
            <div className="text-sm text-gray-500">
              {totalTokens.toLocaleString()} / {maxTokens.toLocaleString()}{" "}
              tokens
            </div>
          </div>
        </div>

        {/* Document List */}
        <DocumentList
          folderId={folderId}
          isLoading={false}
          files={folderDetails.files}
          onRename={handleRenameItem}
          onDelete={handleDeleteItem}
          onDownload={async (documentId: string) => {
            const blob = await downloadItem(documentId);
            const url = URL.createObjectURL(blob);
            window.open(url, "_blank");
          }}
          onUpload={handleUpload}
          onMove={handleMoveFile}
          folders={folders}
          disabled={folderDetails.id === -1}
          editingItemId={editingItemId}
          onSaveRename={handleSaveRename}
          onCancelRename={handleCancelRename}
          newItemName={newItemName}
          setNewItemName={setNewItemName}
          tokenPercentage={tokenPercentage}
          totalTokens={totalTokens}
          maxTokens={maxTokens}
          selectedModelName={getDisplayNameForModel(selectedModel.modelName)}
        />

        {/* File Upload Section */}
      </div>
    </div>
  );
}
