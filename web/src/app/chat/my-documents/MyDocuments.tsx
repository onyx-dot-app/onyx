"use client";

import React, { useMemo, useState, useTransition } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Search, Plus, FolderOpen, Loader2 } from "lucide-react";
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
}

interface SortSelectorProps {
  onSortChange: (sortType: SortType) => void;
}

const SortSelector: React.FC<SortSelectorProps> = ({ onSortChange }) => {
  const [isOpen, setIsOpen] = useState(false);
  const [currentSort, setCurrentSort] = useState<SortType>(
    SortType.TimeCreated
  );

  const handleSortChange = (sortType: SortType) => {
    setCurrentSort(sortType);
    onSortChange(sortType);
    setIsOpen(false);
  };

  return (
    <div className="relative h-fit">
      {isOpen && (
        <div className="absolute right-0 top-full w-48 bg-white rounded-md shadow-lg z-10">
          <div className="py-1">
            {Object.values(SortType).map((sortType) => (
              <button
                key={sortType}
                onClick={() => handleSortChange(sortType)}
                className="block w-full text-left px-4 py-2 text-sm text-neutral-700 hover:bg-neutral-100 focus:outline-none"
              >
                {sortType}
              </button>
            ))}
          </div>
        </div>
      )}

      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center space-x-2 text-sm text-neutral-600 hover:text-neutral-800 focus:outline-none"
      >
        <span>{currentSort}</span>
        <SortIcon className="w-4 h-4" />
      </button>
    </div>
  );
};

const SkeletonLoader = ({ count = 5 }) => (
  <div className={`mt-4 grid gap-3 md:mt-8 md:grid-cols-2 md:gap-6`}>
    {[...Array(count)].map((_, index) => (
      <div
        key={index}
        className="animate-pulse bg-background-200 rounded-xl h-24"
      ></div>
    ))}
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
  const handleSortChange = (sortType: SortType) => {
    setSortType(sortType);
  };
  const pageLimit = 10;
  const searchParams = useSearchParams();
  const router = useRouter();
  const { popup, setPopup } = usePopup();
  const [isCreateFolderOpen, setIsCreateFolderOpen] = useState(false);
  const [isPending, startTransition] = useTransition();

  const folderIdFromParams = parseInt(searchParams.get("folder") || "0", 10);

  const handleFolderClick = (id: number) => {
    startTransition(() => {
      router.push(`/chat/my-documents/${id}`);
      setPage(1);
      setCurrentFolder(id);
    });
  };

  const handleCreateFolder = async (name: string, description: string) => {
    try {
      const folderResponse = await createFolder(name, description);
      // setPopup({
      //   message: "Folder created successfully",
      //   type: "success",
      // });
      // await refreshFolders();
      // setIsCreateFolderOpen(false);
      startTransition(() => {
        router.push(
          `/chat/my-documents/${folderResponse.id}?message=folder-created`
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
        if (sortType === SortType.TimeCreated) {
          return (
            new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
          );
        } else if (sortType === SortType.Alphabetical) {
          return a.name.localeCompare(b.name);
        }
        return 0;
      });
  }, [folders, searchQuery, sortType]);

  return (
    <div className="min-h-full w-full min-w-0 flex-1 mx-auto mt-4 w-full max-w-5xl flex-1 px-4 pb-20 md:pl-8 lg:mt-6 md:pr-8 2xl:pr-14">
      <header className="flex  w-full items-center justify-between gap-4  pt-2  -translate-y-px">
        <h1 className=" flex items-center gap-1.5 text-lg font-medium leading-tight tracking-tight max-md:hidden">
          Knowledge Groups
        </h1>
        <div className="flex items-center gap-2">
          <CreateEntityModal
            title="Create New Knowledge Group"
            entityName="Knowledge Group"
            open={isCreateFolderOpen}
            setOpen={setIsCreateFolderOpen}
            onSubmit={handleCreateFolder}
            trigger={
              <Button className="inline-flex items-center justify-center relative shrink-0 h-9 px-4 py-2 rounded-lg min-w-[5rem] active:scale-[0.985] whitespace-nowrap pl-2 pr-3 gap-1">
                <Plus className="h-5 w-5" />
                New Group
              </Button>
            }
          />
        </div>
      </header>
      <main className="w-full mt-4">
        <div className=" top-3 w-full z-[5] flex gap-4 bg-gradient-to-b via-50% max-lg:flex-col lg:sticky lg:items-center">
          <div className="flex justify-between  w-full ">
            <div className="bg-background-000 dark:bg-neutral-800 border md:max-w-96 border-border-200 dark:border-neutral-700 hover:border-border-100 dark:hover:border-neutral-600 transition-colors placeholder:text-text-500 dark:placeholder:text-neutral-400 focus:border-accent-secondary-100 focus-within:!border-accent-secondary-100 focus:ring-0 focus:outline-none disabled:cursor-not-allowed disabled:opacity-50 h-11 px-3 rounded-[0.6rem] w-full inline-flex cursor-text items-stretch gap-2">
              <div className="flex items-center">
                <Search className="h-4 w-4 text-text-400 dark:text-neutral-400" />
              </div>
              <input
                type="text"
                placeholder="Search groups..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full placeholder:text-text-500 dark:placeholder:text-neutral-400 m-0 bg-transparent p-0 focus:outline-none focus:ring-0 disabled:cursor-not-allowed disabled:opacity-50"
              />
            </div>
            <SortSelector onSortChange={handleSortChange} />
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
            <div
              className={`mt-4 grid gap-3 md:mt-8 ${
                true ? "md:grid-cols-2" : ""
              } md:gap-6 transition-all duration-300 ease-in-out`}
            >
              {filteredFolders.map((folder) => (
                <SharedFolderItem
                  key={folder.id}
                  folder={folder}
                  onClick={handleFolderClick}
                  description={folder.description}
                  lastUpdated={folder.created_at}
                  onRename={() => onRenameItem(folder.id, folder.name, true)}
                  onDelete={() => handleDeleteItem(folder.id, true)}
                  onMove={() => handleMoveItem(folder.id, currentFolder, true)}
                />
              ))}
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-64">
              <FolderOpen
                className="w-20 h-20 text-orange-400 dark:text-orange-300 mb-4 "
                strokeWidth={1.5}
              />
              <p className="text-text-500 dark:text-neutral-400 text-lg font-normal">
                No items found
              </p>
            </div>
          )}
          <div className="mt-3 flex">
            <div className="mx-auto">
              <PageSelector
                currentPage={page}
                totalPages={Math.ceil((folders?.length || 0) / pageLimit)}
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
      </main>
    </div>
  );
}
