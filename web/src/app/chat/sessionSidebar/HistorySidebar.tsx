"use client";

import { FiEdit, FiFolderPlus, FiMoreHorizontal, FiPlus } from "react-icons/fi";
import React, {
  ForwardedRef,
  forwardRef,
  useContext,
  useState,
  useCallback,
} from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ChatSession } from "../interfaces";
import { NEXT_PUBLIC_NEW_CHAT_DIRECTS_TO_SAME_PERSONA } from "@/lib/constants";
import { Folder } from "../folders/interfaces";
import { usePopup } from "@/components/admin/connectors/Popup";
import { SettingsContext } from "@/components/settings/SettingsProvider";

import {
  AssistantsIconSkeleton,
  DocumentIcon2,
  NewChatIcon,
  OnyxIcon,
  PinnedIcon,
  PlusIcon,
} from "@/components/icons/icons";
import { PagesTab } from "./PagesTab";
import { pageType } from "./types";
import LogoWithText from "@/components/header/LogoWithText";
import { Persona } from "@/app/admin/assistants/interfaces";
import { DragEndEvent } from "@dnd-kit/core";
import { useAssistants } from "@/components/context/AssistantsContext";
import { AssistantIcon } from "@/components/assistants/AssistantIcon";
import { buildChatUrl } from "../lib";
import { toggleAssistantPinnedStatus } from "@/lib/assistants/pinnedAssistants";
import { useUser } from "@/components/user/UserProvider";
import { DragHandle } from "@/components/table/DragHandle";
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { reorderPinnedAssistants } from "@/lib/assistants/pinnedAssistants";
import { CircleX } from "lucide-react";

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
  setShowAssistantsModal: (show: boolean) => void;
}

interface SortableAssistantProps {
  assistant: Persona;
  currentAssistantId: number | null | undefined;
  onClick: () => void;
  onUnpin: (e: React.MouseEvent) => void;
}

const SortableAssistant: React.FC<SortableAssistantProps> = ({
  assistant,
  currentAssistantId,
  onClick,
  onUnpin,
}) => {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: assistant.id === 0 ? "assistant-0" : assistant.id });

  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    ...(isDragging ? { zIndex: 1000, position: "relative" as const } : {}),
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...attributes}
      {...listeners}
      className="flex items-center group"
    >
      <DragHandle
        size={16}
        className="w-3 ml-[2px] mr-[2px] group-hover:visible invisible flex-none cursor-grab"
      />
      <button
        onClick={(e) => {
          e.preventDefault();
          if (!isDragging) {
            onClick();
          }
        }}
        className={`cursor-pointer w-full group hover:bg-background-chat-hover ${
          currentAssistantId === assistant.id
            ? "bg-background-chat-hover/60"
            : ""
        } relative flex items-center gap-x-2 py-1 px-2 rounded-md`}
      >
        <AssistantIcon assistant={assistant} size={16} className="flex-none" />
        <p className="text-base text-black">{assistant.name}</p>
        <button
          onClick={(e) => {
            e.stopPropagation();
            onUnpin(e);
          }}
          className="group-hover:block hidden absolute right-2"
        >
          <CircleX size={16} className="text-text-history-sidebar-button" />
        </button>
      </button>
    </div>
  );
};

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
    const { refreshUser, user } = useUser();
    const { refreshAssistants, pinnedAssistants, setPinnedAssistants } =
      useAssistants();

    const { popup, setPopup } = usePopup();

    // For determining intial focus state
    const [newFolderId, setNewFolderId] = useState<number | null>(null);

    const currentChatId = currentChatSession?.id;

    const sensors = useSensors(
      useSensor(PointerSensor, {
        activationConstraint: {
          distance: 8,
        },
      }),
      useSensor(KeyboardSensor, {
        coordinateGetter: sortableKeyboardCoordinates,
      })
    );

    const handleDragEnd = useCallback(
      (event: DragEndEvent) => {
        const { active, over } = event;

        if (active.id !== over?.id) {
          setPinnedAssistants((prevAssistants: Persona[]) => {
            const oldIndex = prevAssistants.findIndex(
              (a: Persona) => (a.id === 0 ? "assistant-0" : a.id) === active.id
            );
            const newIndex = prevAssistants.findIndex(
              (a: Persona) => (a.id === 0 ? "assistant-0" : a.id) === over?.id
            );

            const newOrder = arrayMove(prevAssistants, oldIndex, newIndex);

            // Ensure we're sending the correct IDs to the API
            const reorderedIds = newOrder.map((a: Persona) => a.id);
            reorderPinnedAssistants(reorderedIds);

            return newOrder;
          });
        }
      },
      [setPinnedAssistants, reorderPinnedAssistants]
    );

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
            gap-y-4
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
          <div className="px-4 pl-2">
            <LogoWithText
              showArrow={true}
              toggled={toggled}
              page={page}
              toggleSidebar={toggleSidebar}
              explicitlyUntoggle={explicitlyUntoggle}
            />
          </div>
          {page == "chat" && (
            <div className="px-4 px-1 gap-y-1 flex-col text-text-history-sidebar-button flex gap-x-1.5 items-center items-center">
              <Link
                className="w-full px-2 py-1  rounded-md items-center hover:bg-hover cursor-pointer transition-all duration-150 flex gap-x-2"
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
                <p className="my-auto flex font-normal items-center text-base">
                  Start New Chat
                </p>
              </Link>
              {user?.preferences?.shortcut_enabled && (
                <Link
                  className="w-full px-2 py-1  rounded-md items-center hover:bg-hover cursor-pointer transition-all duration-150 flex gap-x-2"
                  href="/chat/input-prompts"
                  onClick={(e) => {
                    if (e.metaKey || e.ctrlKey) {
                      return;
                    }
                    if (handleNewChat) {
                      handleNewChat();
                    }
                  }}
                >
                  <DocumentIcon2
                    size={20}
                    className="flex-none text-text-history-sidebar-button"
                  />
                  <p className="my-auto flex font-normal items-center text-base">
                    Prompt Shortcuts
                  </p>
                </Link>
              )}
            </div>
          )}

          <div>
            <div className="flex px-4 font-normal text-sm gap-x-2 leading-normal text-[#6c6c6c]/80 items-center font-normal leading-normal">
              Assistants
            </div>
            <DndContext
              sensors={sensors}
              collisionDetection={closestCenter}
              onDragEnd={handleDragEnd}
            >
              <SortableContext
                items={pinnedAssistants.map((a) =>
                  a.id === 0 ? "assistant-0" : a.id
                )}
                strategy={verticalListSortingStrategy}
              >
                <div className="flex px-0  mr-4 flex-col gap-y-1 mt-1">
                  {pinnedAssistants.map((assistant: Persona) => (
                    <SortableAssistant
                      key={assistant.id === 0 ? "assistant-0" : assistant.id}
                      assistant={assistant}
                      currentAssistantId={currentAssistantId}
                      onClick={() => {
                        router.push(
                          buildChatUrl(searchParams, null, assistant.id)
                        );
                      }}
                      onUnpin={async (e: React.MouseEvent) => {
                        e.stopPropagation();
                        await toggleAssistantPinnedStatus(
                          pinnedAssistants.map((a) => a.id),
                          assistant.id,
                          false
                        );
                        await refreshUser();
                        await refreshAssistants();
                      }}
                    />
                  ))}
                </div>
              </SortableContext>
            </DndContext>
            <div className="w-full px-4">
              <button
                onClick={() => setShowAssistantsModal(true)}
                className="w-full cursor-pointer text-base text-black hover:bg-background-chat-hover flex items-center gap-x-2 py-1 px-2 rounded-md"
              >
                Explore Assistants
              </button>
            </div>
          </div>

          <PagesTab
            setNewFolderId={setNewFolderId}
            newFolderId={newFolderId}
            showDeleteModal={showDeleteModal}
            showShareModal={showShareModal}
            closeSidebar={removeToggle}
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
