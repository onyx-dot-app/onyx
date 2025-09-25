"use client";

import { useRouter } from "next/navigation";
import { ChatSession } from "@/app/chat/interfaces";
import { useState, useEffect, useContext, useRef, useCallback } from "react";
import {
  deleteChatSession,
  getChatRetentionInfo,
  renameChatSession,
} from "@/app/chat/services/lib";
import { BasicSelectable } from "@/components/BasicClickable";
import Link from "next/link";
import { FiCheck, FiX } from "react-icons/fi";
import { ChatSessionMorePopup } from "./ChatSessionMorePopup";
import { ShareChatSessionModal } from "@/app/chat/components/modal/ShareChatSessionModal";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import { WarningCircle } from "@phosphor-icons/react";
import { CustomTooltip } from "@/components/tooltip/CustomTooltip";
// removed Info tooltip imports as we no longer show custom assistant info icon

export function ChatSessionDisplay({
  chatSession,
  search,
  isSelected,
  closeSidebar,
  showShareModal,
  showDeleteModal,
  isDragging,
  parentFolderName,
  showDragHandle = true,
  projectId,
  isCustomAssistant,
}: {
  chatSession: ChatSession;
  isSelected: boolean;
  search?: boolean;
  closeSidebar?: () => void;
  showShareModal?: (chatSession: ChatSession) => void;
  showDeleteModal?: (chatSession: ChatSession) => void;
  isDragging?: boolean;
  parentFolderName?: string;
  showDragHandle?: boolean;
  projectId?: number;
  isCustomAssistant?: boolean;
}) {
  const router = useRouter();
  const [isHovered, setIsHovered] = useState(false);
  const [isRenamingChat, setIsRenamingChat] = useState(false);
  const [isShareModalVisible, setIsShareModalVisible] = useState(false);
  const [chatName, setChatName] = useState(chatSession.name);
  const settings = useContext(SettingsContext);
  const chatSessionRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const renamingRef = useRef<HTMLDivElement>(null);

  const isMobile = settings?.isMobile;

  const onRename = useCallback(
    async (e?: React.MouseEvent) => {
      if (e) {
        e.preventDefault();
        e.stopPropagation();
      }
      const response = await renameChatSession(chatSession.id, chatName);
      if (response.ok) {
        setIsRenamingChat(false);
        router.refresh();
      } else {
        alert("Failed to rename chat session");
      }
    },
    [chatSession.id, chatName, router]
  );

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        renamingRef.current &&
        !renamingRef.current.contains(event.target as Node) &&
        isRenamingChat
      ) {
        onRename();
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [isRenamingChat, onRename]);

  if (!settings) {
    return <></>;
  }

  const { daysUntilExpiration, showRetentionWarning } = getChatRetentionInfo(
    chatSession,
    settings?.settings
  );

  return (
    <>
      {isShareModalVisible && (
        <ShareChatSessionModal
          chatSessionId={chatSession.id}
          existingSharedStatus={chatSession.shared_status}
          onClose={() => setIsShareModalVisible(false)}
        />
      )}

      <div
        className="bg-transparent animate-in fade-in slide-in-from-left-2 duration-300"
        ref={chatSessionRef}
      >
        <Link
          onMouseEnter={() => {
            setIsHovered(true);
          }}
          onMouseLeave={() => {
            setIsHovered(false);
          }}
          className="flex group items-center w-full relative"
          key={chatSession.id}
          onClick={() => {
            if (settings?.isMobile && closeSidebar) {
              closeSidebar();
            }
          }}
          href={
            search
              ? `/search?searchId=${chatSession.id}`
              : `/chat?chatId=${chatSession.id}`
          }
          scroll={false}
        >
          <BasicSelectable
            padding="extra"
            isHovered={isHovered}
            isDragging={isDragging}
            fullWidth
            selected={isSelected}
            removeColors={isRenamingChat}
          >
            <>
              <div
                className={`flex  ${
                  isRenamingChat ? "-mr-2" : ""
                } text-text-dark text-sm leading-normal relative gap-x-2`}
              >
                {isRenamingChat ? (
                  <div className="flex items-center w-full" ref={renamingRef}>
                    <div className="flex-grow mr-2">
                      <input
                        ref={inputRef}
                        value={chatName}
                        onClick={(e) => {
                          e.preventDefault();
                          e.stopPropagation();
                        }}
                        onChange={(e) => {
                          setChatName(e.target.value);
                        }}
                        onKeyDown={(event) => {
                          event.stopPropagation();

                          if (event.key === "Enter") {
                            onRename();
                            event.preventDefault();
                          }
                        }}
                        className="w-full text-sm bg-transparent border-b border-text-darker outline-none"
                      />
                    </div>
                    <div className="flex text-text-500 flex-none">
                      <button onClick={onRename} className="p-1">
                        <FiCheck size={14} />
                      </button>
                      <button
                        onClick={(e) => {
                          e.preventDefault();
                          e.stopPropagation();
                          setChatName(chatSession.name);
                          setIsRenamingChat(false);
                        }}
                        className="p-1"
                      >
                        <FiX size={14} />
                      </button>
                    </div>
                  </div>
                ) : (
                  <>
                    <p className="break-all font-normal overflow-hidden dark:text-[#D4D4D4] whitespace-nowrap w-full mr-1 relative">
                      {chatName || `Unnamed Chat`}
                      <span
                        className={`absolute right-0 top-0 h-full w-2 bg-gradient-to-r from-transparent 
                        ${
                          isSelected
                            ? "to-background-chat-selected"
                            : isHovered
                              ? "to-background-chat-hover"
                              : "to-background-sidebar"
                        } `}
                      />
                    </p>
                  </>
                )}

                {!isRenamingChat && (
                  <div className="ml-auto my-auto justify-end flex z-30">
                    {!showShareModal && showRetentionWarning && (
                      <CustomTooltip
                        line
                        content={
                          <p>
                            This chat will expire{" "}
                            {daysUntilExpiration < 1
                              ? "today"
                              : `in ${daysUntilExpiration} day${
                                  daysUntilExpiration !== 1 ? "s" : ""
                                }`}
                          </p>
                        }
                      >
                        <div className="mr-1 hover:bg-black/10 p-1 -m-1 rounded z-50">
                          <WarningCircle className="text-warning" />
                        </div>
                      </CustomTooltip>
                    )}
                    {isHovered && (
                      <ChatSessionMorePopup
                        chatSession={chatSession}
                        projectId={projectId}
                        isRenamingChat={isRenamingChat}
                        setIsRenamingChat={setIsRenamingChat}
                        showShareModal={showShareModal}
                        search={search}
                      />
                    )}
                  </div>
                )}
              </div>
            </>
          </BasicSelectable>
        </Link>
      </div>
    </>
  );
}
