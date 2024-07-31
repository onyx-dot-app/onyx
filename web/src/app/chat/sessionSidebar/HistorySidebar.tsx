"use client";

import { FiArrowDown, FiEdit, FiFolderPlus } from "react-icons/fi";
import {
  Dispatch,
  ForwardedRef,
  forwardRef,
  SetStateAction,
  useContext,
  useEffect,
} from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { BasicClickable } from "@/components/BasicClickable";
import { ChatSession } from "../interfaces";

import {
  NEXT_PUBLIC_DO_NOT_USE_TOGGLE_OFF_DANSWER_POWERED,
  NEXT_PUBLIC_NEW_CHAT_DIRECTS_TO_SAME_PERSONA,
} from "@/lib/constants";

import { Folder } from "../folders/interfaces";
import { createFolder } from "../folders/FolderManagement";
import { usePopup } from "@/components/admin/connectors/Popup";
import { SettingsContext } from "@/components/settings/SettingsProvider";

import React from "react";
import { Logo } from "@/components/EEA_Logo";
import { HeaderTitle } from "@/components/header/Header";
import { TbLayoutSidebarRightExpand } from "react-icons/tb";
import {
  AssistantsIcon,
  AssistantsIconSkeleton,
  BackIcon,
  LefToLineIcon,
  RightToLineIcon,
} from "@/components/icons/icons";
import { PagesTab } from "./PagesTab";
import { Tooltip } from "@/components/tooltip/Tooltip";
import KeyboardSymbol from "@/lib/browserUtilities";
import { pageType } from "./types";

interface HistorySidebarProps {
  page: pageType;
  existingChats?: ChatSession[];
  currentChatSession?: ChatSession | null | undefined;
  folders?: Folder[];
  openedFolders?: { [key: number]: boolean };
  toggleSidebar?: () => void;
  toggled?: boolean;
  removeToggle?: () => void;
}

export const HistorySidebar = forwardRef<HTMLDivElement, HistorySidebarProps>(
  (
    {
      toggled,
      page,
      existingChats,
      currentChatSession,
      folders,
      openedFolders,
      toggleSidebar,
      removeToggle,
    },
    ref: ForwardedRef<HTMLDivElement>
  ) => {
    const commandSymbol = KeyboardSymbol();
    const router = useRouter();
    const { popup, setPopup } = usePopup();

    const currentChatId = currentChatSession?.id;

    // prevent the NextJS Router cache from causing the chat sidebar to not
    // update / show an outdated list of chats
    useEffect(() => {
      router.refresh();
    }, [currentChatId]);

    const combinedSettings = useContext(SettingsContext);
    if (!combinedSettings) {
      return null;
    }
    const settings = combinedSettings.settings;
    const enterpriseSettings = combinedSettings.enterpriseSettings;

    return (
      <>
        {popup}

        <div
          ref={ref}
          className={`
            flex
            flex-none
            bg-background-100
            w-full
            border-r 
            border-border 
            flex 
            flex-col relative
            h-screen
            transition-transform`}
        >
          <div className="max-w-full ml-3 mr-3 mt-2 flex flex gap-x-1 items-center my-auto text-text-700 text-xl">
            <div className="mr-1 desktop:invisible mb-auto h-6 w-6">
              <Logo height={24} width={24} />
            </div>

            <div className="desktop:invisible">
              {enterpriseSettings && enterpriseSettings.application_name ? (
                <div>
                  <HeaderTitle>
                    {enterpriseSettings.application_name}
                  </HeaderTitle>
                  {!NEXT_PUBLIC_DO_NOT_USE_TOGGLE_OFF_DANSWER_POWERED && (
                    <p className="text-xs text-subtle">Powered by Danswer</p>
                  )}
                </div>
              ) : (
                <HeaderTitle>GPT Lab</HeaderTitle>
              )}
            </div>

            {toggleSidebar && (
              <Tooltip
                delayDuration={0}
                content={toggled ? `Unpin sidebar` : "Pin sidebar"}
              >
                <button className="my-auto ml-auto" onClick={toggleSidebar}>
                  {!toggled && !combinedSettings.isMobile ? (
                    <RightToLineIcon />
                  ) : (
                    <LefToLineIcon />
                  )}
                </button>
              </Tooltip>
            )}
          </div>

          {page == "chat" && (
            <div className="mx-3 mt-4 gap-y-1 flex-col flex gap-x-1.5 items-center items-center">
              <Link
                href={
                  "/chat" +
                  (NEXT_PUBLIC_NEW_CHAT_DIRECTS_TO_SAME_PERSONA &&
                  currentChatSession
                    ? `?assistantId=${currentChatSession.persona_id}`
                    : "")
                }
                className="w-full p-2 bg-white border-border border rounded items-center hover:bg-background-200 cursor-pointer transition-all duration-150 flex gap-x-2"
              >
                <FiEdit className="flex-none " />
                <p className="my-auto flex items-center text-sm">New Chat</p>
              </Link>

              <button
                onClick={() =>
                  createFolder("New Folder")
                    .then((folderId) => {
                      console.log(`Folder created with ID: ${folderId}`);
                      router.refresh();
                    })
                    .catch((error) => {
                      console.error("Failed to create folder:", error);
                      setPopup({
                        message: `Failed to create folder: ${error.message}`,
                        type: "error",
                      });
                    })
                }
                className="w-full p-2 bg-white border-border border rounded items-center hover:bg-background-200 cursor-pointer transition-all duration-150 flex gap-x-2"
              >
                <FiFolderPlus className="my-auto" />
                <p className="my-auto flex items-center text-sm">New Folder</p>
              </button>

              <Link
                href="/assistants/mine"
                className="w-full p-2 bg-white border-border border rounded items-center hover:bg-background-200 cursor-pointer transition-all duration-150 flex gap-x-2"
              >
                <AssistantsIconSkeleton className="h-4 w-4 my-auto" />
                <p className="my-auto flex items-center text-sm">
                  Manage Assistants
                </p>
              </Link>
            </div>
          )}
          <div className="border-b border-border pb-4 mx-3" />

          <PagesTab
            closeSidebar={removeToggle}
            page={page}
            existingChats={existingChats}
            currentChatId={currentChatId}
            folders={folders}
            openedFolders={openedFolders}
          />
        </div>
      </>
    );
  }
);
HistorySidebar.displayName = "HistorySidebar";
