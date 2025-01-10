import { ChatSession } from "../interfaces";
import {
  createFolder,
  updateFolderName,
  deleteFolder,
  addChatToFolder,
} from "../folders/FolderManagement";
import { Folder } from "../folders/interfaces";
import { usePopup } from "@/components/admin/connectors/Popup";
import { useRouter } from "next/navigation";
import { pageType } from "./types";
import { FiPlus, FiTrash2, FiEdit, FiCheck, FiX } from "react-icons/fi";
import { NEXT_PUBLIC_DELETE_ALL_CHATS_ENABLED } from "@/lib/constants";
import { FolderDropdown } from "../folders/FolderDropdown";
import { ChatSessionDisplay } from "./ChatSessionDisplay";
import { useState, useCallback, useRef } from "react";

export function PagesTab({
  page,
  existingChats,
  currentChatId,
  folders,
  closeSidebar,
  newFolderId,
  showShareModal,
  showDeleteModal,
  showDeleteAllModal,
  setNewFolderId,
}: {
  page: pageType;
  existingChats?: ChatSession[];
  currentChatId?: string;
  folders?: Folder[];
  closeSidebar?: () => void;
  newFolderId: number | null;
  showShareModal?: (chatSession: ChatSession) => void;
  showDeleteModal?: (chatSession: ChatSession) => void;
  showDeleteAllModal?: () => void;
  setNewFolderId: (folderId: number) => void;
}) {
  const { setPopup } = usePopup();
  const router = useRouter();
  const [isCreatingFolder, setIsCreatingFolder] = useState(false);
  const newFolderInputRef = useRef<HTMLInputElement>(null);

  const handleEditFolder = useCallback(
    (folderId: number | "chats", newName: string) => {
      if (folderId === "chats") return; // Don't edit the default "Chats" folder
      updateFolderName(folderId, newName)
        .then(() => {
          router.refresh();
          setPopup({
            message: "Folder updated successfully",
            type: "success",
          });
        })
        .catch((error: Error) => {
          console.error("Failed to update folder:", error);
          setPopup({
            message: `Failed to update folder: ${error.message}`,
            type: "error",
          });
        });
    },
    [router, setPopup]
  );

  const handleDeleteFolder = useCallback(
    (folderId: number | "chats") => {
      if (folderId === "chats") return; // Don't delete the default "Chats" folder
      if (
        confirm(
          "Are you sure you want to delete this folder? This action cannot be undone."
        )
      ) {
        deleteFolder(folderId)
          .then(() => {
            router.refresh();
            setPopup({
              message: "Folder deleted successfully",
              type: "success",
            });
          })
          .catch((error: Error) => {
            console.error("Failed to delete folder:", error);
            setPopup({
              message: `Failed to delete folder: ${error.message}`,
              type: "error",
            });
          });
      }
    },
    [router, setPopup]
  );

  const handleCreateFolder = useCallback(() => {
    setIsCreatingFolder(true);
    setTimeout(() => {
      newFolderInputRef.current?.focus();
    }, 0);
  }, []);

  const handleNewFolderSubmit = useCallback(
    (e: React.FormEvent<HTMLFormElement>) => {
      e.preventDefault();
      const newFolderName = newFolderInputRef.current?.value;
      if (newFolderName) {
        createFolder(newFolderName)
          .then((folderId) => {
            router.refresh();
            setNewFolderId(folderId);
            setPopup({
              message: "Folder created successfully",
              type: "success",
            });
          })
          .catch((error) => {
            console.error("Failed to create folder:", error);
            setPopup({
              message: `Failed to create folder: ${error.message}`,
              type: "error",
            });
          });
      }
      setIsCreatingFolder(false);
    },
    [router, setNewFolderId, setPopup]
  );

  const ungroupedChats =
    existingChats?.filter((chat) => chat.folder_id === null) || [];
  const chatFolder: {
    folder_name: "Chats";
    chat_sessions: ChatSession[];
    folder_id?: "chats";
  } = {
    folder_name: "Chats",
    chat_sessions: ungroupedChats,
    folder_id: "chats",
  };

  const isHistoryEmpty = !existingChats || existingChats.length === 0;

  const handleDrop = useCallback(
    async (folderId: number, chatSessionId: string) => {
      try {
        await addChatToFolder(folderId, chatSessionId);
        router.refresh();
        setPopup({
          message: "Chat added to folder successfully",
          type: "success",
        });
      } catch (error: unknown) {
        console.error("Failed to add chat to folder:", error);
        setPopup({
          message: `Failed to add chat to folder: ${
            error instanceof Error ? error.message : "Unknown error"
          }`,
          type: "error",
        });
      }
    },
    [router, setPopup]
  );

  const renderChatSession = useCallback(
    (chat: ChatSession) => (
      <div
        key={chat.id}
        draggable
        onDragStart={(e) => {
          e.dataTransfer.setData("text/plain", chat.id);
        }}
      >
        <ChatSessionDisplay
          chatSession={chat}
          isSelected={currentChatId === chat.id}
          showShareModal={showShareModal}
          showDeleteModal={showDeleteModal}
          closeSidebar={closeSidebar}
        />
      </div>
    ),
    [currentChatId, showShareModal, showDeleteModal, closeSidebar]
  );

  return (
    <div className="flex flex-col relative h-full overflow-y-auto mb-1 ml-3 miniscroll mobile:pb-40">
      <div
        className={`flex-grow overflow-y-auto ${
          NEXT_PUBLIC_DELETE_ALL_CHATS_ENABLED && "pb-20"
        }`}
      >
        {!isHistoryEmpty && (
          <FolderDropdown
            folder={chatFolder}
            currentChatId={currentChatId}
            showShareModal={showShareModal}
            showDeleteModal={showDeleteModal}
            closeSidebar={closeSidebar}
            onEdit={handleEditFolder}
            onDelete={handleDeleteFolder}
            onDrop={handleDrop}
          >
            {chatFolder.chat_sessions.map(renderChatSession)}
          </FolderDropdown>
        )}

        {folders &&
          folders.length > 0 &&
          folders
            .sort((a, b) => a.display_priority - b.display_priority)
            .map((folder) => (
              <FolderDropdown
                key={folder.folder_id}
                folder={folder}
                currentChatId={currentChatId}
                showShareModal={showShareModal}
                showDeleteModal={showDeleteModal}
                closeSidebar={closeSidebar}
                onEdit={handleEditFolder}
                onDelete={handleDeleteFolder}
                onDrop={handleDrop}
              >
                {folder.chat_sessions.map(renderChatSession)}
              </FolderDropdown>
            ))}

        {isHistoryEmpty && (
          <p className="text-sm mt-2 w-[250px]">
            Try sending a message! Your chat history will appear here.
          </p>
        )}
        {isCreatingFolder ? (
          <form onSubmit={handleNewFolderSubmit} className="mt-2 relative">
            <input
              ref={newFolderInputRef}
              type="text"
              placeholder="Enter folder name"
              className="w-full p-1 text-sm border rounded pr-8"
            />
            <button
              type="button"
              onClick={() => setIsCreatingFolder(false)}
              className="absolute right-2 top-1/2 transform -translate-y-1/2 text-gray-500 hover:text-gray-700"
            >
              <FiX size={16} />
            </button>
          </form>
        ) : (
          <button
            className="flex text-[#6c6c6c] gap-x-1 mt-2"
            onClick={handleCreateFolder}
          >
            <FiPlus className="my-auto" />
            <p className="my-auto flex items-center text-sm">Create Group</p>
          </button>
        )}
      </div>
      {showDeleteAllModal && NEXT_PUBLIC_DELETE_ALL_CHATS_ENABLED && (
        <div className="absolute w-full border-t border-t-border bg-background-100 bottom-0 left-0 p-4">
          <button
            className="w-full py-2 px-4 text-text-600 hover:text-text-800 bg-background-125 border border-border-strong/50 shadow-sm rounded-md transition-colors duration-200 flex items-center justify-center text-sm"
            onClick={showDeleteAllModal}
          >
            <FiTrash2 className="mr-2" size={14} />
            Clear All History
          </button>
        </div>
      )}
    </div>
  );
}
