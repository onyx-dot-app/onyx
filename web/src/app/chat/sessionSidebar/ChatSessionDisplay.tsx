"use client";

import { useRouter } from "next/navigation";
import { ChatSession } from "../interfaces";
import { useState, useEffect, useContext } from "react";
import { deleteChatSession, renameChatSession } from "../lib";
import { DeleteChatModal } from "../modal/DeleteChatModal";
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
import { ShareChatSessionModal } from "../modal/ShareChatSessionModal";
import { CHAT_SESSION_ID_KEY, FOLDER_ID_KEY } from "@/lib/drag/constants";
import { SettingsContext } from "@/components/settings/SettingsProvider";

export function ChatSessionDisplay({
  chatSession,
  search,
  isSelected,
  skipGradient,
  closeSidebar,
}: {
  chatSession: ChatSession;
  isSelected: boolean;
  search?: boolean;
  // needed when the parent is trying to apply some background effect
  // if not set, the gradient will still be applied and cause weirdness
  skipGradient?: boolean;
  closeSidebar?: () => void;
}) {
  const router = useRouter();
  const [isDeletionModalVisible, setIsDeletionModalVisible] = useState(false);
  const [isRenamingChat, setIsRenamingChat] = useState(false);
  const [isMoreOptionsDropdownOpen, setIsMoreOptionsDropdownOpen] =
    useState(false);
  const [isShareModalVisible, setIsShareModalVisible] = useState(false);
  const [chatName, setChatName] = useState(chatSession.name);
  const [delayedSkipGradient, setDelayedSkipGradient] = useState(skipGradient);

  useEffect(() => {
    if (skipGradient) {
      setDelayedSkipGradient(true);
    } else {
      const timer = setTimeout(() => {
        setDelayedSkipGradient(skipGradient);
      }, 300);
      return () => clearTimeout(timer);
    }
  }, [skipGradient]);

  const onRename = async () => {
    const response = await renameChatSession(chatSession.id, chatName);
    if (response.ok) {
      setIsRenamingChat(false);
      router.refresh();
    } else {
      alert("Failed to rename chat session");
    }
  };
  const settings = useContext(SettingsContext);

  return (
    <>
      {isShareModalVisible && (
        <ShareChatSessionModal
          chatSessionId={chatSession.id}
          existingSharedStatus={chatSession.shared_status}
          onClose={() => setIsShareModalVisible(false)}
        />
      )}

      {isDeletionModalVisible && (
        <DeleteChatModal
          onClose={() => setIsDeletionModalVisible(false)}
          onSubmit={async () => {
            const response = await deleteChatSession(chatSession.id);
            if (response.ok) {
              setIsDeletionModalVisible(false);
              // go back to the main page
              router.push("/chat");
            } else {
              alert("Failed to delete chat session");
            }
          }}
          chatSessionName={chatSession.name}
        />
      )}
      <Link
        className="flex my-1 group relative"
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
        draggable="true"
        onDragStart={(event) => {
          event.dataTransfer.setData(
            CHAT_SESSION_ID_KEY,
            chatSession.id.toString()
          );
          event.dataTransfer.setData(
            FOLDER_ID_KEY,
            chatSession.folder_id?.toString() || ""
          );
        }}
      >
        <BasicSelectable padding="extra" fullWidth selected={isSelected}>
          <>
            <div className="flex relative">
              {isRenamingChat ? (
                <input
                  value={chatName}
                  onChange={(e) => setChatName(e.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      onRename();
                      event.preventDefault();
                    }
                  }}
                  className="-my-px px-1 mr-2 w-full rounded"
                />
              ) : (
                <p className="break-all overflow-hidden whitespace-nowrap w-full mr-3 relative">
                  {chatName || `Chat ${chatSession.id}`}
                  <span
                    className={`absolute right-0 top-0 h-full w-8 bg-gradient-to-r from-transparent 
                    ${isSelected ? "to-background-200" : " to-background-100 group-hover:to-background-200"} `}
                  />
                </p>
              )}

              {isSelected &&
                (isRenamingChat ? (
                  <div className="ml-auto my-auto flex">
                    <div
                      onClick={onRename}
                      className={`hover:bg-black/10 p-1 -m-1 rounded`}
                    >
                      <FiCheck size={16} />
                    </div>
                    <div
                      onClick={() => {
                        setChatName(chatSession.name);
                        setIsRenamingChat(false);
                      }}
                      className={`hover:bg-black/10 p-1 -m-1 rounded ml-2`}
                    >
                      <FiX size={16} />
                    </div>
                  </div>
                ) : (
                  <div className="ml-auto my-auto flex z-30">
                    <div>
                      <div
                        onClick={() => {
                          setIsMoreOptionsDropdownOpen(
                            !isMoreOptionsDropdownOpen
                          );
                        }}
                        className={"-m-1"}
                      >
                        <Popover
                          open={isMoreOptionsDropdownOpen}
                          onOpenChange={(open: boolean) =>
                            setIsMoreOptionsDropdownOpen(open)
                          }
                          content={
                            <div className="hover:bg-black/10 p-1 rounded">
                              <FiMoreHorizontal size={16} />
                            </div>
                          }
                          popover={
                            <div className="border border-border rounded-lg bg-background z-50 w-32">
                              <DefaultDropdownElement
                                name="Share"
                                icon={FiShare2}
                                onSelect={() => setIsShareModalVisible(true)}
                              />
                              <DefaultDropdownElement
                                name="Rename"
                                icon={FiEdit2}
                                onSelect={() => setIsRenamingChat(true)}
                              />
                            </div>
                          }
                          requiresContentPadding
                          sideOffset={6}
                          triggerMaxWidth
                        />
                      </div>
                    </div>
                    <div
                      onClick={() => setIsDeletionModalVisible(true)}
                      className={`hover:bg-black/10 p-1 -m-1 rounded ml-2`}
                    >
                      <FiTrash size={16} />
                    </div>
                  </div>
                ))}
            </div>
          </>
        </BasicSelectable>
      </Link>
    </>
  );
}
