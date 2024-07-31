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

export function PagesTab({
  page,
  existingChats,
  currentChatId,
  folders,
  openedFolders,
  closeSidebar,
}: {
  page: pageType;
  existingChats?: ChatSession[];
  currentChatId?: number;
  folders?: Folder[];
  openedFolders?: { [key: number]: boolean };
  closeSidebar?: () => void;
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
    const chatSessionId = parseInt(
      event.dataTransfer.getData(CHAT_SESSION_ID_KEY),
      10
    );
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
    <div className="mb-1 ml-3 relative miniscroll mobile:pb-40 overflow-y-auto h-full">
      {folders && folders.length > 0 && (
        <div className="py-2 border-b border-border">
          <div className="text-xs text-subtle flex pb-0.5 mb-1.5 mt-2 font-bold">
            Chat Folders
          </div>
          <FolderList
            folders={folders}
            currentChatId={currentChatId}
            openedFolders={openedFolders}
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
          <p className="my-2 text-xs text-subtle flex font-bold">
            {page == "chat" && "Chat "}
            {page == "search" && "Search "}
            History
          </p>
        )}
        {isHistoryEmpty ? (
          <p className="text-sm text-subtle mt-2 w-[250px]">
            {page === "search"
              ? "Try running a search! Your search history will appear here."
              : "Try sending a message! Your chat history will appear here."}
          </p>
        ) : (
          Object.entries(groupedChatSessions).map(
            ([dateRange, chatSessions], ind) => {
              if (chatSessions.length > 0) {
                return (
                  <div key={dateRange}>
                    <div
                      className={`text-xs text-subtle ${
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
    </div>
  );
}
