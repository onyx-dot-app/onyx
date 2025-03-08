"use client";

import React, { useMemo, useState, useTransition } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  Search,
  Plus,
  FolderOpen,
  Loader2,
  MessageSquare,
  ArrowUp,
  ArrowDown,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { usePopup } from "@/components/admin/connectors/Popup";
import { PageSelector } from "@/components/PageSelector";
import { SharedFolderItem } from "./components/SharedFolderItem";
import CreateEntityModal from "@/components/modals/CreateEntityModal";
import { useDocumentsContext } from "./DocumentsContext";
import { SortIcon } from "@/components/icons/icons";
import TextView from "@/components/chat/TextView";

enum SortType {
  TimeCreated = "Time Created",
  Alphabetical = "Alphabetical",
  Tokens = "Tokens",
}

enum SortDirection {
  Ascending = "asc",
  Descending = "desc",
}

const SkeletonLoader = () => (
  <div className="flex justify-center items-center w-full h-64">
    <div className="animate-pulse flex flex-col items-center gap-5 w-full">
      <div className="h-28 w-28 rounded-full  from-primary/20 to-primary/30 dark:from-neutral-700 dark:to-neutral-600 flex items-center justify-center">
        <div className="animate-spin rounded-full h-20 w-20 border-t-2 border-b-2 border-r-0 border-l-0 border-primary dark:border-neutral-300"></div>
      </div>
      <div className="space-y-3">
        <div className="h-5 w-56 bg-gradient-to-r from-primary/20 to-primary/30 dark:from-neutral-700 dark:to-neutral-600 rounded-md"></div>
        <div className="h-4 w-40 bg-gradient-to-r from-primary/20 to-primary/30 dark:from-neutral-700 dark:to-neutral-600 rounded-md"></div>
        <div className="h-3 w-32 bg-gradient-to-r from-primary/20 to-primary/30 dark:from-neutral-700 dark:to-neutral-600 rounded-md"></div>
      </div>
    </div>
  </div>
);

export default function MyDocuments() {
  const {
    folders,
    currentFolder,
    presentingDocument,
    searchQuery,
    page,
    refreshFolders,
    createFolder,
    deleteItem,
    moveItem,
    isLoading,
    downloadItem,
    renameItem,
    setCurrentFolder,
    setPresentingDocument,
    setSearchQuery,
    setPage,
  } = useDocumentsContext();

  const [sortType, setSortType] = useState<SortType>(SortType.TimeCreated);
  const [sortDirection, setSortDirection] = useState<SortDirection>(
    SortDirection.Descending
  );
  const pageLimit = 10;
  const searchParams = useSearchParams();
  const router = useRouter();
  const { popup, setPopup } = usePopup();
  const [isCreateFolderOpen, setIsCreateFolderOpen] = useState(false);
  const [isPending, startTransition] = useTransition();

  const handleSortChange = (newSortType: SortType) => {
    if (sortType === newSortType) {
      setSortDirection(
        sortDirection === SortDirection.Ascending
          ? SortDirection.Descending
          : SortDirection.Ascending
      );
    } else {
      setSortType(newSortType);
      setSortDirection(
        newSortType === SortType.Alphabetical
          ? SortDirection.Ascending
          : SortDirection.Descending
      );
    }
  };

  const handleFolderClick = (id: number) => {
    startTransition(() => {
      router.push(`/chat/user-knowledge/${id}`);
      setPage(1);
      setCurrentFolder(id);
    });
  };

  const handleCreateFolder = async (name: string) => {
    try {
      const folderResponse = await createFolder(name);
      startTransition(() => {
        router.push(
          `/chat/user-knowledge/${folderResponse.id}?message=folder-created`
        );
        setPage(1);
        setCurrentFolder(folderResponse.id);
      });
    } catch (error) {
      console.error("Error creating folder:", error);
      setPopup({
        message:
          error instanceof Error
            ? error.message
            : "Failed to create knowledge group",
        type: "error",
      });
    }
  };

  const handleDeleteItem = async (itemId: number, isFolder: boolean) => {
    const itemType = isFolder ? "Knowledge Group" : "File";
    const confirmDelete = window.confirm(
      `Are you sure you want to delete this ${itemType}?`
    );

    if (confirmDelete) {
      try {
        await deleteItem(itemId, isFolder);
        setPopup({
          message: `${itemType} deleted successfully`,
          type: "success",
        });
        await refreshFolders();
      } catch (error) {
        console.error("Error deleting item:", error);
        setPopup({
          message: `Failed to delete ${itemType}`,
          type: "error",
        });
      }
    }
  };

  const handleMoveItem = async (
    itemId: number,
    currentFolderId: number | null,
    isFolder: boolean
  ) => {
    const availableFolders = folders
      .filter((folder) => folder.id !== itemId)
      .map((folder) => `${folder.id}: ${folder.name}`)
      .join("\n");

    const promptMessage = `Enter the ID of the destination folder:\n\nAvailable folders:\n${availableFolders}\n\nEnter 0 to move to the root folder.`;
    const destinationFolderId = prompt(promptMessage);

    if (destinationFolderId !== null) {
      const newFolderId = parseInt(destinationFolderId, 10);
      if (isNaN(newFolderId)) {
        setPopup({
          message: "Invalid folder ID",
          type: "error",
        });
        return;
      }

      try {
        await moveItem(
          itemId,
          newFolderId === 0 ? null : newFolderId,
          isFolder
        );
        setPopup({
          message: `${
            isFolder ? "Knowledge Group" : "File"
          } moved successfully`,
          type: "success",
        });
        await refreshFolders();
      } catch (error) {
        console.error("Error moving item:", error);
        setPopup({
          message: "Failed to move item",
          type: "error",
        });
      }
    }
  };

  const handleDownloadItem = async (documentId: string) => {
    try {
      await downloadItem(documentId);
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
    currentName: string,
    isFolder: boolean
  ) => {
    const newName = prompt(
      `Enter new name for ${isFolder ? "Knowledge Group" : "File"}:`,
      currentName
    );
    if (newName && newName !== currentName) {
      try {
        await renameItem(itemId, newName, isFolder);
        setPopup({
          message: `${
            isFolder ? "Knowledge Group" : "File"
          } renamed successfully`,
          type: "success",
        });
        await refreshFolders();
      } catch (error) {
        console.error("Error renaming item:", error);
        setPopup({
          message: `Failed to rename ${isFolder ? "Knowledge Group" : "File"}`,
          type: "error",
        });
      }
    }
  };

  const filteredFolders = useMemo(() => {
    return folders
      .filter(
        (folder) =>
          folder.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
          folder.description.toLowerCase().includes(searchQuery.toLowerCase())
      )
      .sort((a, b) => {
        let comparison = 0;

        if (sortType === SortType.TimeCreated) {
          comparison =
            new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
        } else if (sortType === SortType.Alphabetical) {
          comparison = a.name.localeCompare(b.name);
        } else if (sortType === SortType.Tokens) {
          const aTokens = a.files.reduce(
            (acc, file) => acc + (file.token_count || 0),
            0
          );
          const bTokens = b.files.reduce(
            (acc, file) => acc + (file.token_count || 0),
            0
          );
          comparison = bTokens - aTokens;
        }

        return sortDirection === SortDirection.Ascending
          ? -comparison
          : comparison;
      });
  }, [folders, searchQuery, sortType, sortDirection]);

  const renderSortIndicator = (columnType: SortType) => {
    if (sortType !== columnType) return null;

    return sortDirection === SortDirection.Ascending ? (
      <ArrowUp className="ml-1 h-3 w-3 inline" />
    ) : (
      <ArrowDown className="ml-1 h-3 w-3 inline" />
    );
  };

  return (
    <div className="min-h-full w-full min-w-0 flex-1 mx-auto mt-4 w-full max-w-[90rem] flex-1 px-4 pb-20 md:pl-8 lg:mt-6 md:pr-8 2xl:pr-14">
      <header className="flex w-full items-center justify-between gap-4 -translate-y-px">
        <h1 className="flex items-center gap-1.5 text-lg font-medium leading-tight tracking-tight max-md:hidden">
          My Documents
        </h1>
        <div className="flex items-center gap-2">
          <CreateEntityModal
            title="New Folder"
            entityName=""
            open={isCreateFolderOpen}
            setOpen={setIsCreateFolderOpen}
            onSubmit={handleCreateFolder}
            trigger={
              <Button className="inline-flex items-center justify-center relative shrink-0 h-9 px-4 py-2 rounded-lg min-w-[5rem] active:scale-[0.985] whitespace-nowrap pl-2 pr-3 gap-1">
                <Plus className="h-5 w-5" />
                New Folder
              </Button>
            }
            hideLabel
          />
        </div>
      </header>
      <main className="w-full mt-4">
        <div className="top-3 w-full z-[5] flex gap-4 bg-gradient-to-b via-50% max-lg:flex-col lg:sticky lg:items-center">
          <div className="flex justify-between w-full">
            <div className="bg-background-000 dark:bg-neutral-800 border md:max-w-96 border-border-200 dark:border-neutral-700 hover:border-border-100 dark:hover:border-neutral-600 transition-colors placeholder:text-text-500 dark:placeholder:text-neutral-400 focus:border-accent-secondary-100 focus-within:!border-accent-secondary-100 focus:ring-0 focus:outline-none disabled:cursor-not-allowed disabled:opacity-50 h-11 px-3 rounded-[0.6rem] w-full inline-flex cursor-text items-stretch gap-2">
              <div className="flex items-center">
                <Search className="h-4 w-4 text-text-400 dark:text-neutral-400" />
              </div>
              <input
                type="text"
                placeholder="Search documllents..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full placeholder:text-text-500 dark:placeholder:text-neutral-400 m-0 bg-transparent p-0 focus:outline-none focus:ring-0 disabled:cursor-not-allowed disabled:opacity-50"
              />
            </div>
          </div>
        </div>

        {isPending && (
          <div className="flex fixed left-20 top-1/3 justify-center items-center mt-4">
            <Loader2 className="h-6 w-6 animate-spin text-primary dark:text-neutral-300" />
          </div>
        )}
        {presentingDocument && (
          <TextView
            presentingDocument={presentingDocument}
            onClose={() => setPresentingDocument(null)}
          />
        )}
        {popup}
        <div className="flex-grow">
          {isLoading ? (
            <SkeletonLoader />
          ) : filteredFolders.length > 0 ? (
            <div className="mt-6">
              <div className="flex items-center border-b border-border dark:border-border-200 py-2 px-4 text-sm font-medium text-text-400 dark:text-neutral-400">
                <button
                  onClick={() => handleSortChange(SortType.Alphabetical)}
                  className="w-[40%] flex items-center hover:text-text-600 dark:hover:text-neutral-200 cursor-pointer transition-colors"
                >
                  Name {renderSortIndicator(SortType.Alphabetical)}
                </button>
                <button
                  onClick={() => handleSortChange(SortType.TimeCreated)}
                  className="w-[30%] flex items-center hover:text-text-600 dark:hover:text-neutral-200 cursor-pointer transition-colors"
                >
                  Last Modified {renderSortIndicator(SortType.TimeCreated)}
                </button>
                <button
                  onClick={() => handleSortChange(SortType.Tokens)}
                  className="w-[30%] flex items-center hover:text-text-600 dark:hover:text-neutral-200 cursor-pointer transition-colors"
                >
                  LLM Tokens {renderSortIndicator(SortType.Tokens)}
                </button>
              </div>
              <div className="flex flex-col">
                {filteredFolders.map((folder) => (
                  <SharedFolderItem
                    key={folder.id}
                    folder={{
                      ...folder,
                      tokens: folder.files.reduce(
                        (acc, file) => acc + (file.token_count || 0),
                        0
                      ),
                    }}
                    onClick={handleFolderClick}
                    description={folder.description}
                    lastUpdated={folder.created_at}
                    onRename={() => onRenameItem(folder.id, folder.name, true)}
                    onDelete={() => handleDeleteItem(folder.id, true)}
                    onMove={() =>
                      handleMoveItem(folder.id, currentFolder, true)
                    }
                  />
                ))}
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-64">
              <FolderOpen
                className="w-20 h-20 text-orange-400 dark:text-orange-300 mb-4"
                strokeWidth={1.5}
              />
              <p className="text-text-500 dark:text-neutral-400 text-lg font-normal">
                No items found
              </p>
            </div>
          )}
        </div>
      </main>
      {/* Chat Button (Fixed to bottom right) */}
      <div className="fixed bottom-8 right-8">
        <Button
          size="lg"
          className="shadow-lg rounded-full hover:shadow-xl transition-shadow"
        >
          <MessageSquare className="w-5 h-5" />
          Chat with all My Documents
        </Button>
      </div>
    </div>
  );
}
