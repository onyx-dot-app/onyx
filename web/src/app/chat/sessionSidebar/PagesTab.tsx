import { ChatSession } from "../interfaces";
import { groupSessionsByDateRange } from "../lib";
import { ChatSessionDisplay } from "./ChatSessionDisplay";
import { removeChatFromFolder } from "../folders/FolderManagement";
import { FolderList } from "../folders/FolderList";
import { Folder } from "../folders/interfaces";
import { CHAT_SESSION_ID_KEY, FOLDER_ID_KEY } from "@/lib/drag/constants";
import { usePopup } from "@/components/admin/connectors/Popup";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { pageType } from "./types";
import { FiTrash2 } from "react-icons/fi";
import { NEXT_PUBLIC_DELETE_ALL_CHATS_ENABLED } from "@/lib/constants";

export function PagesTab({
  page,
  existingChats,
  currentChatId,
  folders,
  openedFolders,
  closeSidebar,
  newFolderId,
  showShareModal,
  showDeleteModal,
  showDeleteAllModal,
}: {
  page: pageType;
  existingChats?: ChatSession[];
  currentChatId?: string;
  folders?: Folder[];
  openedFolders?: { [key: number]: boolean };
  closeSidebar?: () => void;
  newFolderId: number | null;
  showShareModal?: (chatSession: ChatSession) => void;
  showDeleteModal?: (chatSession: ChatSession) => void;
  showDeleteAllModal?: () => void;
}) {
  const groupedChatSessions = existingChats
    ? groupSessionsByDateRange(existingChats)
    : [];

  const { setPopup } = usePopup();
  const router = useRouter();
  const [isDragOver, setIsDragOver] = useState<boolean>(false);

  const handleDropToRemoveFromFolder = async (
    event: React.DragEvent<HTMLDivElement>
  ) => {
    event.preventDefault();
    setIsDragOver(false); // Reset drag over state on drop
    const chatSessionId = event.dataTransfer.getData(CHAT_SESSION_ID_KEY);
    const folderId = event.dataTransfer.getData(FOLDER_ID_KEY);

    if (folderId) {
      try {
        await removeChatFromFolder(parseInt(folderId, 10), chatSessionId);
        router.refresh(); // Refresh the page to reflect the changes
      } catch (error) {
        setPopup({
          message: "Failed to remove chat from folder",
          type: "error",
        });
      }
    }
  };

  const isHistoryEmpty = !existingChats || existingChats.length === 0;

  return (
    <div className="flex flex-col relative h-full overflow-y-auto mb-1 ml-3 miniscroll mobile:pb-40">
      <div
        className={` flex-grow overflow-y-auto ${
          NEXT_PUBLIC_DELETE_ALL_CHATS_ENABLED && "pb-20  "
        }`}
      >
        {folders && folders.length > 0 && (
          <div className="py-2 border-b border-border">
            <div className="text-xs text-subtle flex pb-0.5 mb-1.5 mt-2 font-bold">
              Chat Folders
            </div>
            <FolderList
              newFolderId={newFolderId}
              folders={folders}
              currentChatId={currentChatId}
              openedFolders={openedFolders}
              showShareModal={showShareModal}
              showDeleteModal={showDeleteModal}
            />
          </div>
        )}

        <div
          onDragOver={(event) => {
            event.preventDefault();
            setIsDragOver(true);
          }}
          onDragLeave={() => setIsDragOver(false)}
          onDrop={handleDropToRemoveFromFolder}
          className={`pt-1 transition duration-300 ease-in-out mr-3 ${
            isDragOver ? "bg-hover" : ""
          } rounded-md`}
        >
          {(page == "chat" || page == "search") && (
            <p className="my-2 text-xs text-sidebar-subtle flex font-bold">
              {page == "chat" && "Chat "}
              {page == "search" && "Search "}
              History
            </p>
          )}
          {isHistoryEmpty ? (
            <p className="text-sm mt-2 w-[250px]">
              Try sending a message! Your chat history will appear here.
            </p>
          ) : (
            Object.entries(groupedChatSessions).map(
              ([dateRange, chatSessions], ind) => {
                if (chatSessions.length > 0) {
                  return (
                    <div key={dateRange}>
                      <div
                        className={`text-xs text-text-sidebar-subtle ${
                          ind != 0 && "mt-5"
                        } flex pb-0.5 mb-1.5 font-medium`}
                      >
                        {dateRange}
                      </div>
                      {chatSessions
                        .filter((chat) => chat.folder_id === null)
                        .map((chat) => {
                          const isSelected = currentChatId === chat.id;
                          return (
                            <div key={`${chat.id}-${chat.name}`}>
                              <ChatSessionDisplay
                                showDeleteModal={showDeleteModal}
                                showShareModal={showShareModal}
                                closeSidebar={closeSidebar}
                                search={page == "search"}
                                chatSession={chat}
                                isSelected={isSelected}
                                skipGradient={isDragOver}
                              />
                            </div>
                          );
                        })}
                    </div>
                  );
                }
              }
            )
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
    </div>
  );
}
