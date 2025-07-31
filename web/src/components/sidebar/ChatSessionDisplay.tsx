"use client";

import { useRouter } from "next/navigation";
import { ChatSession } from "@/app/chat/interfaces";
import { useState, useEffect, useContext, useRef, useCallback } from "react";
import {
  deleteChatSession,
  getChatRetentionInfo,
  renameChatSession,
} from "@/app/chat/lib";
import { BasicSelectable } from "@/components/BasicClickable";
import Link from "next/link";
import {
  FiCheck,
  FiEdit2,
  FiMoreHorizontal,
  FiShare2,
  FiTrash,
  FiX,
} from "react-icons/fi";
import { DefaultDropdownElement } from "@/components/Dropdown";
import { Popover } from "@/components/popover/Popover";
import { ShareChatSessionModal } from "@/app/chat/modal/ShareChatSessionModal";
import { CHAT_SESSION_ID_KEY, FOLDER_ID_KEY } from "@/lib/drag/constants";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import { DragHandle } from "@/components/table/DragHandle";
import { WarningCircle } from "@phosphor-icons/react";
import { CustomTooltip } from "@/components/tooltip/CustomTooltip";
import { useChatContext } from "@/components/context/ChatContext";

export function ChatSessionDisplay({
  chatSession,
  search,
  isSelected,
  closeSidebar,
  showShareModal,
  showDeleteModal,
  isDragging,
}: {
  chatSession: ChatSession;
  isSelected: boolean;
  search?: boolean;
  closeSidebar?: () => void;
  showShareModal?: (chatSession: ChatSession) => void;
  showDeleteModal?: (chatSession: ChatSession) => void;
  isDragging?: boolean;
}) {
  const router = useRouter();
  const [isHovered, setIsHovered] = useState(false);
  const [isRenamingChat, setIsRenamingChat] = useState(false);
  const [isShareModalVisible, setIsShareModalVisible] = useState(false);
  const [chatName, setChatName] = useState(chatSession.name);
  const settings = useContext(SettingsContext);
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const chatSessionRef = useRef<HTMLDivElement>(null);
  const [popoverOpen, setPopoverOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const renamingRef = useRef<HTMLDivElement>(null);

  const { refreshChatSessions, refreshFolders } = useChatContext();

  const isMobile = settings?.isMobile;
  const handlePopoverOpenChange = useCallback(
    (open: boolean) => {
      setPopoverOpen(open);
      if (!open) {
        setIsDeleteModalOpen(false);
      }
    },
    [isDeleteModalOpen]
  );

  const handleDeleteClick = useCallback(() => {
    setIsDeleteModalOpen(true);
  }, []);

  const handleCancelDelete = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDeleteModalOpen(false);
    setPopoverOpen(false);
  }, []);

  const handleConfirmDelete = useCallback(
    async (e: React.MouseEvent) => {
      e.preventDefault();
      e.stopPropagation();
      if (showDeleteModal) {
        showDeleteModal(chatSession);
      }
      await deleteChatSession(chatSession.id);
      await refreshChatSessions();
      await refreshFolders();
      setIsDeleteModalOpen(false);
      setPopoverOpen(false);
    },
    [chatSession, showDeleteModal, refreshChatSessions, refreshFolders]
  );

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

  const handleDragStart = (event: React.DragEvent<HTMLAnchorElement>) => {
    event.dataTransfer.setData(CHAT_SESSION_ID_KEY, chatSession.id.toString());
    event.dataTransfer.setData(
      FOLDER_ID_KEY,
      chatSession.folder_id?.toString() || ""
    );
  };

  const handleTouchStart = (event: React.TouchEvent<HTMLDivElement>) => {
    // Prevent default touch behavior
    event.preventDefault();

    // Create a custom event to mimic drag start
    const customEvent = new Event("dragstart", { bubbles: true });
    (customEvent as any).dataTransfer = new DataTransfer();
    (customEvent as any).dataTransfer.setData(
      CHAT_SESSION_ID_KEY,
      chatSession.id.toString()
    );
    (customEvent as any).dataTransfer.setData(
      FOLDER_ID_KEY,
      chatSession.folder_id?.toString() || ""
    );

    // Dispatch the custom event
    event.currentTarget.dispatchEvent(customEvent);
  };

  return (
    <>
      {isShareModalVisible && (
        <ShareChatSessionModal
          chatSessionId={chatSession.id}
          existingSharedStatus={chatSession.shared_status}
          onClose={() => setIsShareModalVisible(false)}
        />
      )}

      <div className="bg-transparent" ref={chatSessionRef}>
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
          draggable={!isMobile}
          onDragStart={!isMobile ? handleDragStart : undefined}
        >
          <div
            className={`${
              isMobile ? "visible" : "invisible group-hover:visible"
            } flex-none`}
            onTouchStart={isMobile ? handleTouchStart : undefined}
          >
            <DragHandle size={16} className="w-3 ml-[4px] mr-[2px]" />
          </div>
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
                          setPopoverOpen(false);
                        }}
                        className="p-1"
                      >
                        <FiX size={14} />
                      </button>
                    </div>
                  </div>
                ) : (
                  <p className="break-all font-normal overflow-hidden dark:text-[#D4D4D4] whitespace-nowrap w-full mr-3 relative">
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
                    {(isHovered || popoverOpen) && (
                      <div>
                        <div
                          onClick={(e) => {
                            e.preventDefault();
                            setPopoverOpen(!popoverOpen);
                          }}
                          className="-my-1"
                        >
                          <Popover
                            open={popoverOpen}
                            onOpenChange={handlePopoverOpenChange}
                            content={
                              <div className="p-1 rounded">
                                <FiMoreHorizontal
                                  onClick={() => setPopoverOpen(true)}
                                  size={16}
                                />
                              </div>
                            }
                            popover={
                              <div
                                className={`border border-border text-text-dark rounded-lg bg-background z-50 ${
                                  isDeleteModalOpen ? "w-64" : "w-32"
                                }`}
                              >
                                {!isDeleteModalOpen ? (
                                  <>
                                    {showShareModal && (
                                      <DefaultDropdownElement
                                        name="Share"
                                        icon={FiShare2}
                                        onSelect={() =>
                                          showShareModal(chatSession)
                                        }
                                      />
                                    )}
                                    {!search && (
                                      <DefaultDropdownElement
                                        name="Rename"
                                        icon={FiEdit2}
                                        onSelect={() => setIsRenamingChat(true)}
                                      />
                                    )}
                                    <DefaultDropdownElement
                                      name="Delete"
                                      icon={FiTrash}
                                      onSelect={handleDeleteClick}
                                    />
                                  </>
                                ) : (
                                  <div className="p-3">
                                    <p className="text-sm mb-3">
                                      Are you sure you want to delete this chat?
                                    </p>
                                    <div className="flex justify-center gap-2">
                                      <button
                                        className="px-3 py-1 text-sm bg-background-200 rounded"
                                        onClick={handleCancelDelete}
                                      >
                                        Cancel
                                      </button>
                                      <button
                                        className="px-3 py-1 text-sm bg-red-500 text-white rounded"
                                        onClick={handleConfirmDelete}
                                      >
                                        Delete
                                      </button>
                                    </div>
                                  </div>
                                )}
                              </div>
                            }
                            requiresContentPadding
                            sideOffset={6}
                            triggerMaxWidth
                          />
                        </div>
                      </div>
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
