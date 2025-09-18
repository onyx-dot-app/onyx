import { ChatSession } from "@/app/chat/interfaces";
import { usePopup } from "@/components/admin/connectors/Popup";
import { useRouter } from "next/navigation";
import { FolderDropdown } from "@/app/chat/components/folders/FolderDropdown";
import { ChatSessionDisplay } from "./ChatSessionDisplay";
import { useCallback } from "react";
import { groupSessionsByDateRange } from "@/app/chat/services/lib";
import React from "react";
import {
  Tooltip,
  TooltipProvider,
  TooltipTrigger,
  TooltipContent,
} from "@/components/ui/tooltip";
import { Search } from "lucide-react";

export function PagesTab({
  existingChats,
  currentChatId,
  closeSidebar,
  showShareModal,
  showDeleteModal,
  toggleChatSessionSearchModal,
}: {
  existingChats?: ChatSession[];
  currentChatId?: string;
  toggleChatSessionSearchModal?: () => void;
  closeSidebar?: () => void;
  showShareModal?: (chatSession: ChatSession) => void;
  showDeleteModal?: (chatSession: ChatSession) => void;
}) {
  const { setPopup, popup } = usePopup();
  const router = useRouter();
  const groupedChatSesssions = groupSessionsByDateRange(existingChats || []);
  const isHistoryEmpty = !existingChats || existingChats.length === 0;

  const renderChatSession = useCallback(
    (chat: ChatSession) => {
      return (
        <div key={chat.id} className="bg-transparent -mr-2">
          <ChatSessionDisplay
            chatSession={chat}
            isSelected={currentChatId === chat.id}
            showShareModal={showShareModal}
            showDeleteModal={showDeleteModal}
            closeSidebar={closeSidebar}
            showDragHandle={false}
          />
        </div>
      );
    },
    [currentChatId, showShareModal, showDeleteModal, closeSidebar]
  );

  return (
    <div className="flex flex-col gap-y-2 flex-grow">
      {popup}
      <div className="px-4 mt-2 group mr-2 bg-background-sidebar dark:bg-transparent z-20">
        <div className="flex group justify-between text-sm text-text-300/80 items-center font-normal leading-normal">
          <p>Chats</p>

          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  className="p-1.5 group-hover:opacity-100 opacity-0 transition duration-200 cursor-pointer hover:bg-accent-background-hovered rounded-md"
                  onClick={() => {
                    toggleChatSessionSearchModal?.();
                  }}
                >
                  <Search
                    className="flex-none text-text-mobile-sidebar"
                    size={18}
                  />
                </button>
              </TooltipTrigger>
              <TooltipContent>Search Chats</TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>
      </div>

      <div className="pl-2 pr-3">
        {!isHistoryEmpty && (
          <>
            {Object.entries(groupedChatSesssions)
              .filter(([groupName, chats]) => chats.length > 0)
              .map(([groupName, chats], index) => (
                <FolderDropdown
                  key={groupName}
                  folder={{
                    folder_name: groupName,
                    chat_sessions: chats,
                    display_priority: index,
                  }}
                  currentChatId={currentChatId}
                  showShareModal={showShareModal}
                  closeSidebar={closeSidebar}
                  index={index}
                >
                  {chats.map((chat) => renderChatSession(chat))}
                </FolderDropdown>
              ))}
          </>
        )}

        {isHistoryEmpty && (
          <p className="text-sm max-w-full mt-2 w-[250px]">
            Try sending a message! Your chat history will appear here.
          </p>
        )}
      </div>
    </div>
  );
}
