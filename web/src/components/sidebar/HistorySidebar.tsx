"use client";

import React, {
  ForwardedRef,
  forwardRef,
  useContext,
  useCallback,
} from "react";
import Link from "next/link";
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
  TooltipProvider,
} from "@/components/ui/tooltip";

import { useRouter, useSearchParams } from "next/navigation";
import { ChatSession } from "@/app/chat/interfaces";
import { Folder } from "@/app/chat/folders/interfaces";
import { SettingsContext } from "@/components/settings/SettingsProvider";

import {
  DocumentIcon2,
  KnowledgeGroupIcon,
  NewChatIcon,
} from "@/components/icons/icons";
import { PagesTab } from "./PagesTab";
import { pageType } from "./types";
import LogoWithText from "@/components/header/LogoWithText";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { DragEndEvent } from "@dnd-kit/core";
import { useAssistants } from "@/components/context/AssistantsContext";
import { AssistantIcon } from "@/components/assistants/AssistantIcon";
import { buildChatUrl } from "@/app/chat/lib";
import { reorderPinnedAssistants } from "@/lib/assistants/updateAssistantPreferences";
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
import { CircleX, PinIcon } from "lucide-react";
import { restrictToVerticalAxis } from "@dnd-kit/modifiers";
import { TruncatedText } from "@/components/ui/truncatedText";

interface HistorySidebarProps {
  liveAssistant?: MinimalPersonaSnapshot | null;
  page: pageType;
  existingChats?: ChatSession[];
  currentChatSession?: ChatSession | null | undefined;
  folders?: Folder[];
  toggleSidebar?: () => void;
  toggled?: boolean;
  removeToggle?: () => void;
  reset?: () => void;
  showShareModal?: (chatSession: ChatSession) => void;
  showDeleteModal?: (chatSession: ChatSession) => void;
  explicitlyUntoggle: () => void;
  setShowAssistantsModal: (show: boolean) => void;
  toggleChatSessionSearchModal?: () => void;
}

interface SortableAssistantProps {
  assistant: MinimalPersonaSnapshot;
  active: boolean;
  onClick: () => void;
  onPinAction: (e: React.MouseEvent) => void;
  pinned?: boolean;
}

const SortableAssistant: React.FC<SortableAssistantProps> = ({
  assistant,
  active,
  onClick,
  onPinAction,
  pinned = true,
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
        className={`w-3 ml-[2px] mr-[2px] group-hover:visible invisible flex-none cursor-grab ${
          !pinned ? "opacity-0" : ""
        }`}
      />
      <div
        data-testid={`assistant-[${assistant.id}]`}
        onClick={(e) => {
          e.preventDefault();
          if (!isDragging) {
            onClick();
          }
        }}
        className={`cursor-pointer w-full group hover:bg-background-chat-hover ${
          active ? "bg-accent-background-selected" : ""
        } relative flex items-center gap-x-2 py-1 px-2 rounded-md`}
      >
        <AssistantIcon assistant={assistant} size={16} className="flex-none" />
        <TruncatedText
          className="text-base mr-4 text-left w-fit line-clamp-1 text-ellipsis text-black dark:text-[#D4D4D4]"
          text={assistant.name}
        />

        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onPinAction(e);
                }}
                className="group-hover:block hidden absolute right-2"
              >
                {pinned ? (
                  <CircleX
                    size={16}
                    className="text-text-history-sidebar-button"
                  />
                ) : (
                  <PinIcon
                    size={16}
                    className="text-text-history-sidebar-button"
                  />
                )}
              </button>
            </TooltipTrigger>
            <TooltipContent>
              {pinned
                ? "Unpin this assistant from the sidebar"
                : "Pin this assistant to the sidebar"}
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </div>
    </div>
  );
};

export const HistorySidebar = forwardRef<HTMLDivElement, HistorySidebarProps>(
  (
    {
      liveAssistant,
      reset = () => null,
      setShowAssistantsModal = () => null,
      toggled,
      page,
      existingChats,
      currentChatSession,
      folders,
      explicitlyUntoggle,
      toggleSidebar,
      removeToggle,
      showShareModal,
      toggleChatSessionSearchModal,
      showDeleteModal,
    },
    ref: ForwardedRef<HTMLDivElement>
  ) => {
    const searchParams = useSearchParams();
    const router = useRouter();
    const { user, toggleAssistantPinnedStatus } = useUser();
    const { refreshAssistants, pinnedAssistants, setPinnedAssistants } =
      useAssistants();

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
          setPinnedAssistants((prevAssistants: MinimalPersonaSnapshot[]) => {
            const oldIndex = prevAssistants.findIndex(
              (a: MinimalPersonaSnapshot) =>
                (a.id === 0 ? "assistant-0" : a.id) === active.id
            );
            const newIndex = prevAssistants.findIndex(
              (a: MinimalPersonaSnapshot) =>
                (a.id === 0 ? "assistant-0" : a.id) === over?.id
            );

            const newOrder = arrayMove(prevAssistants, oldIndex, newIndex);

            // Ensure we're sending the correct IDs to the API
            const reorderedIds = newOrder.map(
              (a: MinimalPersonaSnapshot) => a.id
            );
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
      console.log("currentChatSession", currentChatSession);

      const newChatUrl =
        `/${page}` +
        (currentChatSession
          ? `?assistantId=${currentChatSession.persona_id}`
          : "");
      router.push(newChatUrl);
    };

    return (
      <>
        <div
          ref={ref}
          className={`
            flex
            flex-none
            gap-y-4
            bg-background-sidebar
            w-full
            border-r 
            dark:border-none
            dark:text-[#D4D4D4]
            dark:bg-[#000]
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
            <div className="px-4 px-1 -mx-2 gap-y-1 flex-col text-text-history-sidebar-button flex gap-x-1.5 items-center items-center">
              <Link
                className="w-full px-2 py-1 group rounded-md items-center hover:bg-accent-background-hovered cursor-pointer transition-all duration-150 flex gap-x-2"
                href={
                  `/${page}` +
                  (currentChatSession
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
                <NewChatIcon size={20} className="flex-none" />
                <p className="my-auto flex font-normal  items-center ">
                  New Chat
                </p>
              </Link>
              <Link
                className="w-full px-2 py-1  rounded-md items-center hover:bg-hover cursor-pointer transition-all duration-150 flex gap-x-2"
                href="/chat/my-documents"
              >
                <KnowledgeGroupIcon
                  size={20}
                  className="flex-none text-text-history-sidebar-button"
                />
                <p className="my-auto flex font-normal items-center text-base">
                  My Documents
                </p>
              </Link>
              {user?.preferences?.shortcut_enabled && (
                <Link
                  className="w-full px-2 py-1  rounded-md items-center hover:bg-accent-background-hovered cursor-pointer transition-all duration-150 flex gap-x-2"
                  href="/chat/input-prompts"
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
          <div className="h-full  relative overflow-x-hidden overflow-y-auto">
            <div className="flex px-4 font-normal text-sm gap-x-2 leading-normal text-text-500/80 dark:text-[#D4D4D4] items-center font-normal leading-normal">
              Assistants
            </div>
            <DndContext
              sensors={sensors}
              collisionDetection={closestCenter}
              onDragEnd={handleDragEnd}
              modifiers={[restrictToVerticalAxis]}
            >
              <SortableContext
                items={pinnedAssistants.map((a) =>
                  a.id === 0 ? "assistant-0" : a.id
                )}
                strategy={verticalListSortingStrategy}
              >
                <div className="flex px-0  mr-4 flex-col gap-y-1 mt-1">
                  {pinnedAssistants.map((assistant: MinimalPersonaSnapshot) => (
                    <SortableAssistant
                      key={assistant.id === 0 ? "assistant-0" : assistant.id}
                      assistant={assistant}
                      active={assistant.id === liveAssistant?.id}
                      onClick={() => {
                        router.push(
                          buildChatUrl(searchParams, null, assistant.id)
                        );
                      }}
                      onPinAction={async (e: React.MouseEvent) => {
                        e.stopPropagation();
                        await toggleAssistantPinnedStatus(
                          pinnedAssistants.map((a) => a.id),
                          assistant.id,
                          false
                        );
                        await refreshAssistants();
                      }}
                    />
                  ))}
                </div>
              </SortableContext>
            </DndContext>
            {!pinnedAssistants.some((a) => a.id === liveAssistant?.id) &&
              liveAssistant && (
                <div className="w-full mt-1 pr-4">
                  <SortableAssistant
                    pinned={false}
                    assistant={liveAssistant}
                    active={liveAssistant.id === liveAssistant?.id}
                    onClick={() => {
                      router.push(
                        buildChatUrl(searchParams, null, liveAssistant.id)
                      );
                    }}
                    onPinAction={async (e: React.MouseEvent) => {
                      e.stopPropagation();
                      await toggleAssistantPinnedStatus(
                        [...pinnedAssistants.map((a) => a.id)],
                        liveAssistant.id,
                        true
                      );
                      await refreshAssistants();
                    }}
                  />
                </div>
              )}

            <div className="w-full px-4">
              <button
                aria-label="Explore Assistants"
                onClick={() => setShowAssistantsModal(true)}
                className="w-full cursor-pointer text-base text-black dark:text-[#D4D4D4] hover:bg-background-chat-hover flex items-center gap-x-2 py-1 px-2 rounded-md"
              >
                Explore Assistants
              </button>
            </div>

            <PagesTab
              toggleChatSessionSearchModal={toggleChatSessionSearchModal}
              showDeleteModal={showDeleteModal}
              showShareModal={showShareModal}
              closeSidebar={removeToggle}
              existingChats={existingChats}
              currentChatId={currentChatId}
              folders={folders}
            />
          </div>
        </div>
      </>
    );
  }
);
HistorySidebar.displayName = "HistorySidebar";
