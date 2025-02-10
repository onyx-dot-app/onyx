import React, { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, MessageSquare } from "lucide-react";
import { useDocumentsContext } from "../DocumentsContext";
import { useAssistants } from "@/components/context/AssistantsContext";
import { useChatContext } from "@/components/context/ChatContext";
import { Button } from "@/components/ui/button";
import { DocumentList } from "./components/DocumentList";
import { usePopup } from "@/components/admin/connectors/Popup";
import { usePopupFromQuery } from "@/components/popup/PopupFromQuery";
import { Input } from "@/components/ui/input";
import { DeleteEntityModal } from "@/components/DeleteEntityModal";
import { MoveFolderModal } from "@/components/MoveFolderModal";
import { FolderResponse } from "../DocumentsContext";
import { SharingPanel } from "./components/panels/SharingPanel";
import { ContextLimitPanel } from "./components/panels/ContextLimitPanel";
import { AddWebsitePanel } from "./components/panels/AddWebsitePanel";

export default function UserFolderContent({ folderId }: { folderId: number }) {
  const router = useRouter();
  const { assistants } = useAssistants();
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
  } = useDocumentsContext();

  const [isCapacityOpen, setIsCapacityOpen] = useState(false);
  const [isSharedOpen, setIsSharedOpen] = useState(false);
  const [editingItemId, setEditingItemId] = useState<number | null>(null);
  const [newItemName, setNewItemName] = useState("");
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
    router.push("/chat/my-documents");
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
      router.push(`/chat/my-documents/${targetFolderId}`);
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
    <div className="min-h-full w-full min-w-0 flex-1 mx-auto max-w-5xl px-4 pb-20 md:pl-8 mt-6 md:pr-8 2xl:pr-14">
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
      <div className="flex justify-between items-start mb-6">
        <div className="flex-1 mr-4">
          <div
            className="flex text-sm mb-4 items-center cursor-pointer text-neutral-700 dark:text-neutral-300"
            onClick={handleBack}
          >
            <ArrowLeft className="h-4 w-4 mr-2" /> Back to My Knowledge Groups
          </div>
          {editingItemId === folderDetails.id ? (
            <div className="flex items-center">
              <Input
                value={newItemName}
                onChange={(e) => setNewItemName(e.target.value)}
                className="mr-2"
              />
              <Button
                onClick={() => handleSaveRename(folderDetails.id, true)}
                className="mr-2"
              >
                Save
              </Button>
              <Button onClick={handleCancelRename} variant="outline">
                Cancel
              </Button>
            </div>
          ) : (
            <div className="flex items-center">
              <h1
                className="flex items-center gap-1.5 text-lg font-medium leading-tight tracking-tight max-md:hidden cursor-pointer mr-4 text-neutral-900 dark:text-neutral-100"
                onClick={() =>
                  handleRenameItem(folderDetails.id, folderDetails.name, true)
                }
              >
                {folderDetails.name}
              </h1>
            </div>
          )}
          <p className="text-neutral-600 dark:text-neutral-200 mb-4">
            {folderDetails.description}
          </p>

          <DocumentList
            isLoading={false}
            files={folderDetails.files}
            onRename={handleRenameItem}
            onDelete={handleDeleteItem}
            onDownload={downloadItem}
            onUpload={handleUpload}
            onMove={handleMoveFile}
            folders={folders}
            disabled={folderDetails.id === -1}
            editingItemId={editingItemId}
            onSaveRename={handleSaveRename}
            onCancelRename={handleCancelRename}
            newItemName={newItemName}
            setNewItemName={setNewItemName}
          />
        </div>

        <div className="w-[313.33px] bg-[#fff] dark:bg-neutral-800 mt-20 relative rounded-md border border-neutral-200 dark:border-neutral-700 overflow-hidden">
          <ContextLimitPanel
            isOpen={isCapacityOpen}
            onToggle={() => setIsCapacityOpen(!isCapacityOpen)}
            tokenPercentage={tokenPercentage}
            totalTokens={totalTokens}
            maxTokens={maxTokens}
            selectedModel={selectedModel}
            modelDescriptors={modelDescriptors}
            onSelectModel={setSelectedModel}
          />

          <SharingPanel
            assistantIds={folderDetails.assistant_ids}
            assistants={assistants}
            isOpen={isSharedOpen}
            onToggle={() => setIsSharedOpen(!isSharedOpen)}
          />

          <AddWebsitePanel
            folderId={folderId}
            onCreateFileFromLink={handleCreateFileFromLink}
          />

          <div className="p-4">
            <Button
              variant="default"
              className="w-full"
              onClick={handleStartChat}
            >
              <MessageSquare className="w-4 h-4 mr-2" />
              Chat with This Group
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
