"use client";

import React, { useEffect, useMemo, useState, useTransition } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  Plus,
  FolderOpen,
  MessageSquare,
  ArrowUp,
  ArrowDown,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { usePopup } from "@/components/admin/connectors/Popup";
import { SharedFolderItem } from "./components/SharedFolderItem";
import CreateEntityModal from "@/components/modals/CreateEntityModal";
import { useDocumentsContext } from "./DocumentsContext";
import TextView from "@/components/chat/TextView";
import { TokenDisplay } from "@/components/TokenDisplay";
import { useChatContext } from "@/components/context/ChatContext";

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

  const searchParams = useSearchParams();

  const router = useRouter();
  const { popup, setPopup } = usePopup();
  const [isCreateFolderOpen, setIsCreateFolderOpen] = useState(false);

  useEffect(() => {
    const createFolder = searchParams.get("createFolder");
    if (createFolder) {
      setIsCreateFolderOpen(true);
      const newSearchParams = new URLSearchParams(searchParams);
      newSearchParams.delete("createFolder");
      router.replace(`?${newSearchParams.toString()}`);
    }
  }, [searchParams]);

  const [isPending, startTransition] = useTransition();
  const [hoveredColumn, setHoveredColumn] = useState<SortType | null>(null);

  const handleSortChange = (newSortType: SortType) => {
    if (sortType === newSortType) {
      setSortDirection(
        sortDirection === SortDirection.Ascending
          ? SortDirection.Descending
          : SortDirection.Ascending
      );
    } else {
      setSortType(newSortType);
      setSortDirection(SortDirection.Descending);
    }
  };

  const handleFolderClick = (id: number) => {
    startTransition(() => {
      router.push(`/chat/my-documents/${id}`);
      setPage(1);
      setCurrentFolder(id);
    });
  };

  const handleCreateFolder = async (name: string) => {
    try {
      const folderResponse = await createFolder(name);
      startTransition(() => {
        setPage(1);
        setIsCreateFolderOpen(false);
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
    try {
      await deleteItem(itemId, isFolder);
      setPopup({
        message: isFolder
          ? `Folder deleted successfully`
          : `File deleted successfully`,
        type: "success",
      });
      await refreshFolders();
    } catch (error) {
      console.error("Error deleting item:", error);
      setPopup({
        message: `Failed to delete ${isFolder ? "folder" : "file"}`,
        type: "error",
      });
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

  const renderHoverIndicator = (columnType: SortType) => {
    if (sortType === columnType || hoveredColumn !== columnType) return null;

    return <ArrowDown className="ml-1 h-3 w-3 inline opacity-70" />;
  };

  const handleStartChat = () => {
    router.push(`/chat?allMyDocuments=true`);
  };

  const totalTokens = folders.reduce(
    (acc, folder) =>
      acc +
      (folder.files.reduce((acc, file) => acc + (file.token_count || 0), 0) ||
        0),
    0
  );
  const { llmProviders } = useChatContext();

  const modelDescriptors = llmProviders.flatMap((provider) =>
    provider.model_configurations.map((modelConfiguration) => ({
      modelName: modelConfiguration.name,
      provider: provider.provider,
      maxTokens: modelConfiguration.max_input_tokens!,
    }))
  );

  const selectedModel = modelDescriptors[0] || {
    modelName: "Unknown",
    provider: "Unknown",
    maxTokens: 0,
  };
  const maxTokens = selectedModel.maxTokens;
  const tokenPercentage = (totalTokens / maxTokens) * 100;

  return (
    <div className="min-h-full pt-20 w-full min-w-0 flex-1 mx-auto  w-full max-w-[90rem] flex-1 px-4 pb-20 md:pl-8  md:pr-8 2xl:pr-14">
      <header className="flex w-full items-center justify-between gap-4 -translate-y-px">
        <h1 className="flex items-center gap-1.5 text-lg font-medium leading-tight tracking-tight max-md:hidden">
          My Documents
        </h1>
        <div className="flex items-center gap-2">
          <CreateEntityModal
            title="New Folder"
            entityName=""
            open={isCreateFolderOpen}
            placeholder="Untitled folder"
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

      <main className="w-full pt-3 -mt-[1px]">
        <div className="mb-6">
          <div className="relative w-full max-w-xl">
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
            <input
              type="text"
              placeholder="Search documents..."
              className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-md focus:outline-none"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>
        </div>

        {presentingDocument && (
          <TextView
            presentingDocument={presentingDocument}
            onClose={() => setPresentingDocument(null)}
          />
        )}
        {popup}
        <div className="flex justify-between items-center mb-6">
          <div className="flex items-center space-x-2">
            <Button
              onClick={handleStartChat}
              className="flex items-center gap-2 p-4 bg-black rounded-full !text-xs text-white hover:bg-neutral-800"
            >
              <MessageSquare className="w-3 h-3" />
              Chat with My Documents
            </Button>
            <TokenDisplay
              totalTokens={totalTokens}
              maxTokens={maxTokens}
              tokenPercentage={tokenPercentage}
              selectedModel={selectedModel}
            />
          </div>
        </div>

        <div className="flex-grow">
          {isLoading ? (
            <SkeletonLoader />
          ) : filteredFolders.length > 0 ? (
            <div className="mt-6">
              <div className="flex pr-12 items-center border-b border-border dark:border-border-200 py-2 px-4 text-sm font-medium text-text-600 dark:text-neutral-400">
                <button
                  onClick={() => handleSortChange(SortType.Alphabetical)}
                  onMouseEnter={() => setHoveredColumn(SortType.Alphabetical)}
                  onMouseLeave={() => setHoveredColumn(null)}
                  className="w-[40%] flex items-center cursor-pointer transition-colors"
                >
                  Name {renderSortIndicator(SortType.Alphabetical)}
                  {renderHoverIndicator(SortType.Alphabetical)}
                </button>
                <button
                  onClick={() => handleSortChange(SortType.TimeCreated)}
                  onMouseEnter={() => setHoveredColumn(SortType.TimeCreated)}
                  onMouseLeave={() => setHoveredColumn(null)}
                  className="w-[30%] flex items-center cursor-pointer transition-colors"
                >
                  Last Modified {renderSortIndicator(SortType.TimeCreated)}
                  {renderHoverIndicator(SortType.TimeCreated)}
                </button>
                <button
                  onClick={() => handleSortChange(SortType.Tokens)}
                  onMouseEnter={() => setHoveredColumn(SortType.Tokens)}
                  onMouseLeave={() => setHoveredColumn(null)}
                  className="w-[30%] flex items-center cursor-pointer transition-colors"
                >
                  LLM Tokens {renderSortIndicator(SortType.Tokens)}
                  {renderHoverIndicator(SortType.Tokens)}
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
                    onDelete={() => handleDeleteItem(folder.id, true)}
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
    </div>
  );
}
