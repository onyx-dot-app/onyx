"use client";

import { FiEdit, FiFolderPlus } from "react-icons/fi";
import React, { ForwardedRef, forwardRef, useContext, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ChatSession } from "../interfaces";
import { NEXT_PUBLIC_NEW_CHAT_DIRECTS_TO_SAME_PERSONA } from "@/lib/constants";
import { Folder } from "../folders/interfaces";
import { createFolder } from "../folders/FolderManagement";
import { usePopup } from "@/components/admin/connectors/Popup";
import { SettingsContext } from "@/components/settings/SettingsProvider";

import { AssistantsIconSkeleton } from "@/components/icons/icons";
import { PagesTab } from "./PagesTab";
import { pageType } from "./types";
import LogoWithText from "@/components/header/LogoWithText";

interface HistorySidebarProps {
  page: pageType;
  existingChats?: ChatSession[];
  currentChatSession?: ChatSession | null | undefined;
  folders?: Folder[];
  openedFolders?: { [key: number]: boolean };
  toggleSidebar?: () => void;
  toggled?: boolean;
  removeToggle?: () => void;
  reset?: () => void;
  showShareModal?: (chatSession: ChatSession) => void;
  showDeleteModal?: (chatSession: ChatSession) => void;
  stopGenerating?: () => void;
  explicitlyUntoggle: () => void;
  showDeleteAllModal?: () => void;
  backgroundToggled?: boolean;
}

export const HistorySidebar = forwardRef<HTMLDivElement, HistorySidebarProps>(
  (
    {
      reset = () => null,
      toggled,
      page,
      existingChats,
      currentChatSession,
      folders,
      openedFolders,
      explicitlyUntoggle,
      toggleSidebar,
      removeToggle,
      stopGenerating = () => null,
      showShareModal,
      showDeleteModal,
      showDeleteAllModal,
      backgroundToggled,
    },
    ref: ForwardedRef<HTMLDivElement>
  ) => {
    const router = useRouter();
    const { popup, setPopup } = usePopup();

    // For determining intial focus state
    const [newFolderId, setNewFolderId] = useState<number | null>(null);

    const currentChatId = currentChatSession?.id;

    // NOTE: do not do something like the below - assume that the parent
    // will handle properly refreshing the existingChats
    // useEffect(() => {
    //   router.refresh();
    // }, [currentChatId]);

    const combinedSettings = useContext(SettingsContext);
    if (!combinedSettings) {
      return null;
    }

    const handleNewChat = () => {
      reset();
      const newChatUrl =
        `/${page}` +
        (NEXT_PUBLIC_NEW_CHAT_DIRECTS_TO_SAME_PERSONA && currentChatSession
          ? `?assistantId=${currentChatSession.persona_id}`
          : "");
      router.push(newChatUrl);
    };

    return (
      <>
        {popup}
        <div
          ref={ref}
          className={`
            flex
            flex-none
            bg-background-sidebar
            w-full
            border-r 
            border-sidebar-border 
            flex 
            flex-col relative
            h-screen
            pt-2
            transition-transform 
            `}
        >
          <div className="pl-2">
            <LogoWithText
              showArrow={true}
              toggled={toggled}
              page={page}
              toggleSidebar={toggleSidebar}
              explicitlyUntoggle={explicitlyUntoggle}
            />
          </div>
          {page == "chat" && (
            <div className="mx-3 mt-4 gap-y-1 flex-col text-text-history-sidebar-button flex gap-x-1.5 items-center items-center">
              <Link
                className=" w-full p-2 bg-white border-border border rounded items-center hover:bg-background-200 cursor-pointer transition-all duration-150 flex gap-x-2"
                href={
                  `/${page}` +
                  (NEXT_PUBLIC_NEW_CHAT_DIRECTS_TO_SAME_PERSONA &&
                  currentChatSession?.persona_id
                    ? `?assistantId=${currentChatSession?.persona_id}`
                    : "")
                }
                onClick={(e) => {
                  if (e.metaKey || e.ctrlKey) {
                    return;
                  }
                  if (handleNewChat) {
                    handleNewChat();
                  }
                }}
              >
                <FiEdit className="flex-none text-text-history-sidebar-button" />
                <p className="my-auto flex items-center text-sm">New Chat</p>
              </Link>
              <button
                onClick={() =>
                  createFolder("New Folder")
                    .then((folderId) => {
                      router.refresh();
                      setNewFolderId(folderId);
                    })
                    .catch((error) => {
                      console.error("Failed to create folder:", error);
                      setPopup({
                        message: `Failed to create folder: ${error.message}`,
                        type: "error",
                      });
                    })
                }
                className="w-full p-2 bg-white border-border border rounded items-center  hover:bg-background-history-sidebar-button-hover cursor-pointer transition-all duration-150 flex gap-x-2"
              >
                <FiFolderPlus className="my-auto text-text-history-sidebar-button" />
                <p className="my-auto flex items-center text-sm">New Folder</p>
              </button>

              <Link
                href="/assistants/mine"
                className="w-full p-2 bg-white border-border border rounded items-center hover:bg-background-history-sidebar-button-hover cursor-pointer transition-all duration-150 flex gap-x-2"
              >
                <AssistantsIconSkeleton className="h-4 w-4 my-auto text-text-history-sidebar-button" />
                <p className="my-auto flex items-center text-sm">
                  Manage Assistants
                </p>
              </Link>
            </div>
          )}
          <div className="border-b border-divider-history-sidebar-bar pb-4 mx-3" />
          <PagesTab
            newFolderId={newFolderId}
            showDeleteModal={showDeleteModal}
            showShareModal={showShareModal}
            closeSidebar={removeToggle}
            page={page}
            existingChats={existingChats}
            currentChatId={currentChatId}
            folders={folders}
            openedFolders={openedFolders}
            showDeleteAllModal={showDeleteAllModal}
          />
        </div>
      </>
    );
  }
);
HistorySidebar.displayName = "HistorySidebar";
