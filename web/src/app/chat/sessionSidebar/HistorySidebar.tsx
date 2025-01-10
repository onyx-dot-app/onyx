"use client";

import { FiEdit, FiFolderPlus, FiMoreHorizontal } from "react-icons/fi";
import React, { ForwardedRef, forwardRef, useContext, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ChatSession } from "../interfaces";
import { NEXT_PUBLIC_NEW_CHAT_DIRECTS_TO_SAME_PERSONA } from "@/lib/constants";
import { Folder } from "../folders/interfaces";
import { createFolder } from "../folders/FolderManagement";
import { usePopup } from "@/components/admin/connectors/Popup";
import { SettingsContext } from "@/components/settings/SettingsProvider";

import {
  AssistantsIconSkeleton,
  NewChatIcon,
  OnyxIcon,
  PinnedIcon,
  PlusIcon,
} from "@/components/icons/icons";
import { PagesTab } from "./PagesTab";
import { pageType } from "./types";
import LogoWithText from "@/components/header/LogoWithText";
import { Persona } from "@/app/admin/assistants/interfaces";
import { FaSearch } from "react-icons/fa";
import { useAssistants } from "@/components/context/AssistantsContext";
import { AssistantIcon } from "@/components/assistants/AssistantIcon";
import { buildChatUrl } from "../lib";

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
  assistants: Persona[];
  currentAssistantId?: number | null;
  setShowAssistantsModal?: (show: boolean) => void;
}

export const HistorySidebar = forwardRef<HTMLDivElement, HistorySidebarProps>(
  (
    {
      reset = () => null,
      setShowAssistantsModal = () => null,
      toggled,
      page,
      existingChats,
      currentChatSession,
      assistants,
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
      currentAssistantId,
    },
    ref: ForwardedRef<HTMLDivElement>
  ) => {
    const searchParams = useSearchParams();
    const router = useRouter();
    const { popup, setPopup } = usePopup();

    // For determining intial focus state
    const [newFolderId, setNewFolderId] = useState<number | null>(null);

    const currentChatId = currentChatSession?.id;
    const { pinnedAssistants } = useAssistants();

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
                className="w-full p-2 rounded items-center  cursor-pointer transition-all duration-150 flex gap-x-2"
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
                <NewChatIcon
                  size={20}
                  className="flex-none text-text-history-sidebar-button"
                />
                <p className="my-auto flex items-center text-base">
                  Start New Chat
                </p>
              </Link>
            </div>
          )}

          <div className="my-2 mx-3">
            <div className="flex text-sm gap-x-2 mx-2 items-center">
              <PinnedIcon
                className="text-text-history-sidebar-button"
                size={12}
              />
              Pinned
            </div>
            <div className="flex flex-col gap-y-1 mt-2">
              {pinnedAssistants.slice(0, 3).map((assistant) => (
                <button
                  onClick={() => {
                    router.push(buildChatUrl(searchParams, null, assistant.id));

                    // router.push(`/${page}?assistantId=${assistant.id}`);
                  }}
                  className={`cursor-pointer hover:bg-hover-light ${
                    currentAssistantId === assistant.id ? "bg-hover-light" : ""
                  } flex items-center gap-x-2 py-1 px-2 rounded-md`}
                  key={assistant.id}
                >
                  <AssistantIcon
                    assistant={assistant}
                    size={16}
                    className="flex-none"
                  />
                  <p className="text-base text-black">{assistant.name}</p>
                </button>
              ))}
              <button
                onClick={() => setShowAssistantsModal(true)}
                className="cursor-pointer hover:bg-hover-light flex items-center gap-x-2 py-1 px-2 rounded-md"
              >
                <FiMoreHorizontal size={16} className="flex-none" />
                <p className="text-base text-black">More Assistants</p>
              </button>
            </div>
          </div>

          <PagesTab
            setNewFolderId={setNewFolderId}
            newFolderId={newFolderId}
            showDeleteModal={showDeleteModal}
            showShareModal={showShareModal}
            closeSidebar={removeToggle}
            page={page}
            existingChats={existingChats}
            currentChatId={currentChatId}
            folders={folders}
            showDeleteAllModal={showDeleteAllModal}
          />
        </div>
      </>
    );
  }
);
HistorySidebar.displayName = "HistorySidebar";
