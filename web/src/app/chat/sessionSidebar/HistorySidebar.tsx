"use client";

import React, {
  ForwardedRef,
  forwardRef,
  useContext,
  useState,
  useCallback,
  useLayoutEffect,
  useRef,
} from "react";
import Link from "next/link";
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
  TooltipProvider,
} from "@/components/ui/tooltip";

import { useRouter, useSearchParams } from "next/navigation";
import { ChatSession } from "../interfaces";
import { NEXT_PUBLIC_NEW_CHAT_DIRECTS_TO_SAME_PERSONA } from "@/lib/constants";
import { Folder } from "../folders/interfaces";
import { usePopup } from "@/components/admin/connectors/Popup";
import { SettingsContext } from "@/components/settings/SettingsProvider";

import { DocumentIcon2, NewChatIcon } from "@/components/icons/icons";
import { PagesTab } from "./PagesTab";
import { pageType } from "./types";
import LogoWithText from "@/components/header/LogoWithText";
import { Persona } from "@/app/admin/assistants/interfaces";
import { DragEndEvent } from "@dnd-kit/core";
import { useAssistants } from "@/components/context/AssistantsContext";
import { AssistantIcon } from "@/components/assistants/AssistantIcon";
import { buildChatUrl } from "../lib";
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
import { CircleX } from "lucide-react";
import { restrictToVerticalAxis } from "@dnd-kit/modifiers";

interface HistorySidebarProps {
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
  showDeleteAllModal?: () => void;
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

  const nameRef = useRef<HTMLParagraphElement>(null);
  const hiddenNameRef = useRef<HTMLSpanElement>(null);
  const [isNameTruncated, setIsNameTruncated] = useState(false);

  useLayoutEffect(() => {
    const checkTruncation = () => {
      if (nameRef.current && hiddenNameRef.current) {
        const visibleWidth = nameRef.current.offsetWidth;
        const fullTextWidth = hiddenNameRef.current.offsetWidth;
        setIsNameTruncated(fullTextWidth > visibleWidth);
      }
    };

    checkTruncation();
    window.addEventListener("resize", checkTruncation);
    return () => window.removeEventListener("resize", checkTruncation);
  }, [assistant.name]);

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
        <AssistantIcon assistant={assistant} size={20} className="flex-none" />
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <p
                ref={nameRef}
                className="text-base text-left w-fit line-clamp-1 text-ellipsis text-black"
              >
                {assistant.name}
              </p>
            </TooltipTrigger>
            {isNameTruncated && (
              <TooltipContent>{assistant.name}</TooltipContent>
            )}
          </Tooltip>
        </TooltipProvider>
        <span
          ref={hiddenNameRef}
          className="absolute left-[-9999px] whitespace-nowrap"
        >
          {assistant.name}
        </span>
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
      folders,
      explicitlyUntoggle,
      toggleSidebar,
      removeToggle,
      showShareModal,
      showDeleteModal,
      showDeleteAllModal,
      currentAssistantId,
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

          <div className="h-full relative overflow-x-hidden overflow-y-auto">
            <div className="flex px-4 font-normal text-sm gap-x-2 leading-normal text-[#6c6c6c]/80 items-center font-normal leading-normal">
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

            <PagesTab
              showDeleteModal={showDeleteModal}
              showShareModal={showShareModal}
              closeSidebar={removeToggle}
              existingChats={existingChats}
              currentChatId={currentChatId}
              folders={folders}
              showDeleteAllModal={showDeleteAllModal}
            />
          </div>
        </div>
      </>
    );
  }
);
HistorySidebar.displayName = "HistorySidebar";
