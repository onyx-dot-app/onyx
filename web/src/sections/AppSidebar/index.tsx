"use client";

import React, {
  useCallback,
  useState,
  memo,
  useMemo,
  useRef,
  useEffect,
} from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useSettingsContext } from "@/components/settings/SettingsProvider";
import { SEARCH_PARAM_NAMES } from "@/app/chat/services/searchParams";
import { OnyxLogoTypeIcon, OnyxIcon } from "@/components/icons/icons";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import Text from "@/components-2/Text";
import { DragEndEvent } from "@dnd-kit/core";
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
import SvgSidebar from "@/icons/sidebar";
import SvgEditBig from "@/icons/edit-big";
import SvgMoreHorizontal from "@/icons/more-horizontal";
import SvgLightbulbSimple from "@/icons/lightbulb-simple";
import Settings from "@/sections/AppSidebar/Settings";
import {
  AgentsMenu,
  MenuButton,
  SidebarButton,
  SidebarSection,
} from "@/sections/AppSidebar/components";
import AgentsModal from "@/sections/AgentsModal";
import { useChatContext } from "@/components/context/ChatContext";
import SvgBubbleText from "@/icons/bubble-text";
import {
  buildChatUrl,
  deleteChatSession,
  renameChatSession,
} from "@/app/chat/services/lib";
import { useAgentsContext } from "@/components-2/context/AgentsContext";
import { useAppSidebarContext } from "@/components-2/context/AppSidebarContext";
import { ModalIds, useModal } from "@/components-2/context/ModalContext";
import { useClickOutside } from "@/hooks/useClickOutside";
import { ChatSession } from "@/app/chat/interfaces";
import ConfirmationModal from "@/components-2/modals/ConfirmationModal";
import SvgTrash from "@/icons/trash";
import SvgShare from "@/icons/share";
import SvgEdit from "@/icons/edit";
import Truncated from "@/components-2/Truncated";
import Button from "@/components-2/Button";

// Visible-agents = pinned-agents + current-agent (if current-agent not in pinned-agents)
// OR Visible-agents = pinned-agents (if current-agent in pinned-agents)
function buildVisibleAgents(
  pinnedAgents: MinimalPersonaSnapshot[],
  currentAgent: MinimalPersonaSnapshot | null
): [MinimalPersonaSnapshot[], boolean] {
  if (!currentAgent) return [pinnedAgents, false];
  const currentAgentIsPinned = pinnedAgents.some(
    (pinnedAgent) => pinnedAgent.id === currentAgent.id
  );
  const visibleAgents = currentAgentIsPinned
    ? pinnedAgents
    : [...pinnedAgents, currentAgent];
  return [visibleAgents, currentAgentIsPinned];
}

interface ChatButtonProps {
  chatSession: ChatSession;
  onChatSessionClick: (chatSessionId: string | null) => void;
}

function ChatButtonInner({ chatSession, onChatSessionClick }: ChatButtonProps) {
  const searchParams = useSearchParams();
  const [kebabMenuOpen, setKebabMenuOpen] = useState(false);
  const [renamingChat, setRenamingChat] = useState(false);
  const [deleteConfirmationModalOpen, setDeleteConfirmationModalOpen] =
    useState(false);
  const [chatName, setChatName] = useState(chatSession.name);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const currentChatId = searchParams.get(SEARCH_PARAM_NAMES.CHAT_ID);
  const { refreshChatSessions } = useChatContext();

  useEffect(() => {
    if (renamingChat && textareaRef.current) {
      textareaRef.current.focus();
      textareaRef.current.select();
    }
  }, [renamingChat]);

  // Handle click outside to abort rename
  useClickOutside(
    textareaRef,
    () => {
      // Reset to original name and exit rename mode
      setRenamingChat(false);
    },
    renamingChat
  );

  const handleSaveRename = useCallback(async () => {
    const newChatName = chatName.trim();

    if (newChatName && newChatName !== chatSession.name) {
      try {
        await renameChatSession(chatSession.id, newChatName);
        await refreshChatSessions();
      } catch (error) {
        console.error("Failed to rename chat:", error);
      }
    }
    setRenamingChat(false);
  }, [chatName, chatSession.id, chatSession.name]);

  const handleChatDelete = useCallback(async () => {
    try {
      await deleteChatSession(chatSession.id);
      await refreshChatSessions();
    } catch (error) {
      console.error("Failed to delete chat:", error);
    }
  }, [chatSession, deleteChatSession, refreshChatSessions]);

  return (
    <>
      {deleteConfirmationModalOpen && (
        <ConfirmationModal
          title="Delete Chat"
          icon={SvgTrash}
          description="Are you sure you want to delete this chat? This action cannot be undone."
          onClose={() => setDeleteConfirmationModalOpen(false)}
        >
          <div className="flex flex-row justify-end items-center gap-spacing-interline">
            <Button
              onClick={() => setDeleteConfirmationModalOpen(false)}
              secondary
            >
              Cancel
            </Button>
            <Button
              danger
              onClick={() => {
                setDeleteConfirmationModalOpen(false);
                handleChatDelete();
              }}
            >
              Delete
            </Button>
          </div>
        </ConfirmationModal>
      )}

      <SidebarButton
        key={chatSession.id}
        icon={SvgBubbleText}
        active={currentChatId === chatSession.id}
        onClick={() => onChatSessionClick(chatSession.id)}
        kebabMenu={
          <div className="flex flex-col gap-spacing-inline">
            <MenuButton icon={SvgShare}>Share</MenuButton>
            <MenuButton
              icon={SvgEdit}
              onClick={() => {
                setKebabMenuOpen(false);
                setRenamingChat(true);
              }}
            >
              Rename
            </MenuButton>
            <div className="border-b mx-padding-button" />
            <MenuButton
              icon={SvgTrash}
              onClick={() => {
                setKebabMenuOpen(false);
                setDeleteConfirmationModalOpen(true);
              }}
              danger
            >
              Delete
            </MenuButton>
          </div>
        }
        kebabMenuOpen={kebabMenuOpen}
        setKebabMenuOpen={setKebabMenuOpen}
        disableKebabHover={renamingChat}
        className={
          renamingChat ? "border-[0.125rem] border-text-04" : undefined
        }
      >
        {renamingChat ? (
          <textarea
            ref={textareaRef}
            value={chatName}
            onChange={(event) => setChatName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                handleSaveRename();
              } else if (event.key === "Escape") {
                event.preventDefault();
                setRenamingChat(false);
              }
            }}
            className="bg-transparent outline-none resize-none h-auto overflow-x-auto overflow-y-hidden whitespace-nowrap no-scrollbar font-main-body"
            rows={1}
          />
        ) : chatSession.name ? (
          chatSession.name
        ) : (
          <Truncated>
            <Text text01>Unnamed Chat</Text>
          </Truncated>
        )}
      </SidebarButton>
    </>
  );
}

const ChatButton = memo(ChatButtonInner);

interface AgentsButtonProps {
  visibleAgent: MinimalPersonaSnapshot;
  currentAgent: MinimalPersonaSnapshot | null;
  onAgentClick: (agentId: number) => void;
  onTogglePin: (agent: MinimalPersonaSnapshot, pinned: boolean) => void;
}

function AgentsButtonInner({
  visibleAgent,
  currentAgent,
  onAgentClick,
  onTogglePin,
}: AgentsButtonProps) {
  const { pinnedAgents } = useAgentsContext();
  const pinned = pinnedAgents.some(
    (pinnedAgent) => pinnedAgent.id === visibleAgent.id
  );

  const [kebabMenuOpen, setKebabMenuOpen] = useState(false);

  return (
    <SortableItem id={visibleAgent.id}>
      <SidebarButton
        icon={SvgLightbulbSimple}
        kebabMenu={
          <AgentsMenu
            pinned={pinned}
            onTogglePin={() => onTogglePin(visibleAgent, !pinned)}
          />
        }
        kebabMenuOpen={kebabMenuOpen}
        setKebabMenuOpen={setKebabMenuOpen}
        active={currentAgent?.id === visibleAgent.id}
        onClick={() => onAgentClick(visibleAgent.id)}
      >
        {visibleAgent.name}
      </SidebarButton>
    </SortableItem>
  );
}

const AgentsButton = memo(AgentsButtonInner);

interface SortableItemProps {
  id: number;
  children?: React.ReactNode;
}

function SortableItem({ id, children }: SortableItemProps) {
  const { attributes, listeners, setNodeRef, transform, isDragging } =
    useSortable({ id });

  return (
    <div
      ref={setNodeRef}
      style={{
        transform: CSS.Transform.toString(transform),
        zIndex: 1000,
        ...(isDragging && { zIndex: 1000, position: "relative" as const }),
      }}
      {...attributes}
      {...listeners}
      className="flex items-center group"
    >
      {children}
    </div>
  );
}

function AppSidebarInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { pinnedAgents, setPinnedAgents, togglePinnedAgent, currentAgent } =
    useAgentsContext();
  const { folded, setFolded, foldedAndHovered, setHovered } =
    useAppSidebarContext();
  const { toggleModal } = useModal();
  const { chatSessions } = useChatContext();
  const combinedSettings = useSettingsContext();

  const currentChatId = searchParams?.get(SEARCH_PARAM_NAMES.CHAT_ID);

  const [visibleAgents, currentAgentIsPinned] = useMemo(
    () => buildVisibleAgents(pinnedAgents, currentAgent),
    [pinnedAgents, currentAgent]
  );
  const visibleAgentIds = useMemo(
    () => visibleAgents.map((agent) => agent.id),
    [visibleAgents]
  );

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
      if (!over) return;
      if (active.id === over.id) return;

      setPinnedAgents((prev) => {
        const activeIndex = visibleAgentIds.findIndex(
          (agentId) => agentId === active.id
        );
        const overIndex = visibleAgentIds.findIndex(
          (agentId) => agentId === over.id
        );

        if (currentAgent && !currentAgentIsPinned) {
          // This is the case in which the user is dragging the UNPINNED agent and moving it to somewhere else in the list.
          // This is an indication that we WANT to pin this agent!
          if (activeIndex === visibleAgentIds.length - 1) {
            const prevWithVisible = [...prev, currentAgent];
            return arrayMove(prevWithVisible, activeIndex, overIndex);
          }
        }

        return arrayMove(prev, activeIndex, overIndex);
      });
    },
    [visibleAgentIds, setPinnedAgents, currentAgent, currentAgentIsPinned]
  );

  const handleChatSessionClick = useCallback(
    (chatSessionId: string | null) => {
      router.push(buildChatUrl(searchParams, chatSessionId || null, null));
    },
    [router, searchParams]
  );

  const handleAgentClick = useCallback(
    (agentId: number) => {
      router.push(buildChatUrl(searchParams, null, agentId));
    },
    [router, searchParams]
  );

  const isHistoryEmpty = useMemo(
    () => !chatSessions || chatSessions.length === 0,
    [chatSessions]
  );

  if (!combinedSettings) {
    return null;
  }

  return (
    <>
      <AgentsModal />

      <div
        className={`h-screen ${folded ? "w-[4rem]" : "w-[15rem]"} flex flex-col bg-background-tint-02 ${folded ? "px-spacing-interline" : "px-padding-button"} py-padding-content flex-shrink-0 gap-padding-content`}
        onMouseOver={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
      >
        {/* Header - fixed height */}
        <div
          className={`flex flex-row items-center px-spacing-interline py-spacing-inline ${folded ? "justify-center" : "justify-between"} flex-shrink-0`}
        >
          {folded ? (
            <div className="h-[1.6rem] flex flex-col items-center justify-center">
              {foldedAndHovered ? (
                <SvgSidebar
                  className="cursor-pointer hover:stroke-text-04 stroke-text-03 w-[1rem]"
                  onClick={() => setFolded(false)}
                />
              ) : (
                <OnyxIcon size={24} />
              )}
            </div>
          ) : (
            <>
              <OnyxLogoTypeIcon size={88} />
              <SvgSidebar
                className="cursor-pointer hover:stroke-text-04 stroke-text-03 w-[1rem]"
                onClick={() => {
                  setFolded(true);
                  setHovered(false);
                }}
              />
            </>
          )}
        </div>

        <SidebarButton
          icon={SvgEditBig}
          hideTitle={folded}
          onClick={() => handleChatSessionClick(null)}
          active={!currentChatId && !currentAgent}
        >
          New Session
        </SidebarButton>

        {/* Scrollable content area - takes remaining space */}
        <div className="flex flex-col gap-padding-content flex-1 overflow-y-scroll">
          {!folded && (
            <>
              {/* Agents */}
              <SidebarSection title="Agents">
                <DndContext
                  sensors={sensors}
                  collisionDetection={closestCenter}
                  onDragEnd={handleDragEnd}
                >
                  <SortableContext
                    items={visibleAgentIds}
                    strategy={verticalListSortingStrategy}
                  >
                    {visibleAgents.map((visibleAgent) => (
                      <AgentsButton
                        key={visibleAgent.id}
                        visibleAgent={visibleAgent}
                        currentAgent={currentAgent}
                        onAgentClick={handleAgentClick}
                        onTogglePin={togglePinnedAgent}
                      />
                    ))}
                  </SortableContext>
                </DndContext>
                <SidebarButton
                  icon={SvgMoreHorizontal}
                  grey
                  onClick={() => toggleModal(ModalIds.AgentsModal, true)}
                >
                  More Agents
                </SidebarButton>
              </SidebarSection>

              {/* Recents */}
              <SidebarSection title="Recents">
                {isHistoryEmpty ? (
                  <Text text01 className="px-padding-button">
                    Try sending a message! Your chat history will appear here.
                  </Text>
                ) : (
                  chatSessions.map((chatSession) => (
                    <ChatButton
                      key={chatSession.id}
                      chatSession={chatSession}
                      onChatSessionClick={handleChatSessionClick}
                    />
                  ))
                )}
              </SidebarSection>
            </>
          )}
        </div>

        {/* Footer - fixed height */}
        <div className="flex flex-col flex-shrink-0">
          <Settings folded={folded} />
        </div>
      </div>
    </>
  );
}

const AppSidebar = memo(AppSidebarInner);
AppSidebar.displayName = "AppSidebar";

export default AppSidebar;
