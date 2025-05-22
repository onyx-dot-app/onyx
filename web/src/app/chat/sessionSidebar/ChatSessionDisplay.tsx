"use client";

import { useRouter } from "next/navigation";
import { ChatSession } from "../interfaces";
import { useState, useEffect, useContext, useRef, useCallback } from "react";
import {
  deleteChatSession,
  getChatRetentionInfo,
  renameChatSession,
} from "../lib";
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
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { ShareChatSessionModal } from "../modal/ShareChatSessionModal";
import { CHAT_SESSION_ID_KEY, FOLDER_ID_KEY } from "@/lib/drag/constants";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import { WarningCircle } from "@phosphor-icons/react";
import { CustomTooltip } from "@/components/tooltip/CustomTooltip";
import { useChatContext } from "@/components/context/ChatContext";
import Text from "@/components/ui/text";
import { Button } from "@/components/ui/button";

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
  const inputRef = useRef<HTMLInputElement>(null);
  const renamingRef = useRef<HTMLDivElement>(null);
  const [popoverOpen, setPopoverOpen] = useState(false);

  const { refreshChatSessions, refreshFolders } = useChatContext();

  const isMobile = settings?.isMobile;

  const handleDeleteClick = useCallback(() => {
    setIsDeleteModalOpen(true);
  }, []);

  const handleCancelDelete = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setPopoverOpen(false);
    setIsDeleteModalOpen(false);
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
      setPopoverOpen(false);
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

  return (
    <>
      {isShareModalVisible && (
        <ShareChatSessionModal
          chatSessionId={chatSession.id}
          existingSharedStatus={chatSession.shared_status}
          onClose={() => {
            setIsShareModalVisible(false);
            setPopoverOpen(false);
          }}
        />
      )}

      <div className="bg-transparent" ref={chatSessionRef}>
        <Link
          onMouseEnter={() => {
            setIsHovered(true);
          }}
          onMouseLeave={() => {
            setIsHovered(false);
            setIsDeleteModalOpen(false);
            setPopoverOpen(false);
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
          <BasicSelectable
            padding="extra"
            isHovered={isHovered}
            isDragging={isDragging}
            fullWidth
            selected={isSelected}
            removeColors={isRenamingChat}
          >
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
                        } else if (event.key === "Escape") {
                          setIsRenamingChat(false);
                          setPopoverOpen(false);
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
                  {isHovered && (
                    <Popover open={popoverOpen}>
                      <PopoverTrigger
                        asChild
                        onClick={() => setPopoverOpen(!popoverOpen)}
                      >
                        <FiMoreHorizontal size={16} />
                      </PopoverTrigger>
                      <PopoverContent
                        className={`p-0 ${
                          isDeleteModalOpen ? "w-[250px]" : "w-[150px]"
                        }`}
                      >
                        {isDeleteModalOpen ? (
                          <div className="p-4 flex flex-col gap-y-4">
                            <Text>
                              Are you sure you want to delete this chat?
                            </Text>
                            <div className="px-2 flex flex-1 flex-row justify-center gap-x-2">
                              <Button
                                variant="destructive"
                                onClick={handleConfirmDelete}
                              >
                                Delete
                              </Button>
                              <Button onClick={handleCancelDelete}>
                                Cancel
                              </Button>
                            </div>
                          </div>
                        ) : (
                          <>
                            {showShareModal && (
                              <DefaultDropdownElement
                                name="Share"
                                icon={FiShare2}
                                onSelect={() => showShareModal(chatSession)}
                              />
                            )}
                            {!search && (
                              <DefaultDropdownElement
                                name="Rename"
                                icon={FiEdit2}
                                onSelect={() => {
                                  setIsRenamingChat(true);
                                  setTimeout(() => {
                                    inputRef.current?.focus();
                                  }, 0);
                                }}
                              />
                            )}
                            <DefaultDropdownElement
                              name="Delete"
                              icon={FiTrash}
                              onSelect={handleDeleteClick}
                            />
                          </>
                        )}
                      </PopoverContent>
                    </Popover>
                  )}
                </div>
              )}
            </div>
          </BasicSelectable>
        </Link>
      </div>
    </>
  );
}
