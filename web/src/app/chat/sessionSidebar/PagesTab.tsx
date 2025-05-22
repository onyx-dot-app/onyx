import { ChatSession } from "../interfaces";
import {
  createFolder,
  updateFolderName,
  deleteFolder,
  addChatToFolder,
  updateFolderDisplayPriorities,
} from "../folders/FolderManagement";
import { Folder } from "../folders/interfaces";
import { usePopup } from "@/components/admin/connectors/Popup";
import { useRouter } from "next/navigation";
import { FiPlus, FiCheck, FiX } from "react-icons/fi";
import { ChatSessionDisplay } from "./ChatSessionDisplay";
import { useState, useCallback, useRef, useContext, useEffect } from "react";
import { groupSessionsByDateRange } from "../lib";
import React from "react";
import {
  Tooltip,
  TooltipProvider,
  TooltipTrigger,
  TooltipContent,
} from "@/components/ui/tooltip";
import { Expand, ListTree, Search } from "lucide-react";
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  DragEndEvent,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { useChatContext } from "@/components/context/ChatContext";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import { restrictToVerticalAxis } from "@dnd-kit/modifiers";
import { Separator } from "@/components/ui/separator";
import ChatGroup, { ChatGroupProps } from "./ChatGroup";
import {
  SidebarContent,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarProvider,
} from "@/components/ui/sidebar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

function ToolTipHelper({
  icon,
  toolTipContent,
  onClick,
}: {
  icon: React.ReactNode;
  toolTipContent: string;
  onClick?: () => void;
}) {
  return (
    <TooltipProvider delayDuration={1000}>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="ghost"
            className="border-0 border-red-50 px-2"
            onClick={onClick}
          >
            {icon}
          </Button>
        </TooltipTrigger>
        <TooltipContent>{toolTipContent}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

function SortableChatGroup(props: ChatGroupProps) {
  const settings = useContext(SettingsContext);
  const mobile = settings?.isMobile;
  const [isDragging, setIsDragging] = useState(false);
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging: isDraggingDndKit,
  } = useSortable({
    id: props.folderId?.toString() ?? "",
    disabled: mobile,
  });

  useEffect(() => {
    setIsDragging(isDraggingDndKit);
  }, [isDraggingDndKit]);

  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  // const ref = useRef<HTMLDivElement>(null);

  return (
    <div style={style} {...listeners} ref={setNodeRef} {...attributes}>
      <ChatGroup {...props} />
    </div>
  );
}

export function PagesTab({
  existingChats,
  currentChatId,
  folders,
  closeSidebar,
  showShareModal,
  showDeleteModal,
  toggleChatSessionSearchModal,
}: {
  existingChats?: ChatSession[];
  currentChatId?: string;
  folders?: Folder[];
  toggleChatSessionSearchModal?: () => void;
  closeSidebar?: () => void;
  showShareModal?: (chatSession: ChatSession) => void;
  showDeleteModal?: (chatSession: ChatSession) => void;
}) {
  const { setPopup, popup } = usePopup();
  const router = useRouter();
  const [isCreatingFolder, setIsCreatingFolder] = useState(false);
  const newFolderInputRef = useRef<HTMLInputElement>(null);
  const { reorderFolders, refreshFolders, refreshChatSessions } =
    useChatContext();

  const handleEditFolder = useCallback(
    async (folderId: number, newName: string) => {
      try {
        await updateFolderName(folderId, newName);
        setPopup({
          message: "Folder updated successfully",
          type: "success",
        });
        await refreshFolders();
      } catch (error) {
        console.error("Failed to update folder:", error);
        setPopup({
          message: `Failed to update folder: ${(error as Error).message}`,
          type: "error",
        });
      }
    },
    [router, setPopup, refreshFolders]
  );

  const handleDeleteFolder = useCallback(
    async (folderId: number) => {
      try {
        await deleteFolder(folderId);
        setPopup({
          message: "Folder deleted successfully",
          type: "success",
        });
        await refreshFolders();
      } catch (error: any) {
        console.error("Failed to delete folder:", error);
        setPopup({
          message: `Failed to delete folder: ${(error as Error).message}`,
          type: "error",
        });
      }
    },
    [router, setPopup, refreshFolders]
  );

  const handleCreateFolder = useCallback(() => {
    setIsCreatingFolder(true);
    setTimeout(() => {
      newFolderInputRef.current?.focus();
    }, 0);
  }, []);

  const handleNewFolderSubmit = useCallback(
    async (e: React.FormEvent<HTMLDivElement>) => {
      e.preventDefault();
      const newFolderName = newFolderInputRef.current?.value;
      if (newFolderName) {
        try {
          await createFolder(newFolderName);
          await refreshFolders();
          router.refresh();
          setPopup({
            message: "Folder created successfully",
            type: "success",
          });
        } catch (error) {
          console.error("Failed to create folder:", error);
          setPopup({
            message:
              error instanceof Error
                ? error.message
                : "Failed to create folder",
            type: "error",
          });
        }
      }
      setIsCreatingFolder(false);
    },
    [router, setPopup, refreshFolders]
  );

  const existingChatsNotinFolders = existingChats?.filter(
    (chat) =>
      !folders?.some((folder) =>
        folder.chat_sessions?.some((session) => session.id === chat.id)
      )
  );

  const groupedChatSesssions = groupSessionsByDateRange(
    existingChatsNotinFolders || []
  );

  const handleDrop = useCallback(
    async (folderId: number, chatSessionId: string) => {
      try {
        await addChatToFolder(folderId, chatSessionId);
        router.refresh();
        setPopup({
          message: "Chat added to folder successfully",
          type: "success",
        });
      } catch (error: unknown) {
        console.error("Failed to add chat to folder:", error);
        setPopup({
          message: `Failed to add chat to folder: ${
            error instanceof Error ? error.message : "Unknown error"
          }`,
          type: "error",
        });
      }
      // await refreshChatSessions();
      await refreshFolders();
    },
    [router, setPopup]
  );

  const [isDraggingSessionId, setIsDraggingSessionId] = useState<string | null>(
    null
  );

  const renderChatSession = useCallback(
    (chat: ChatSession, foldersExisting: boolean) => {
      return (
        <div
          key={chat.id}
          className="-ml-4 bg-transparent  -mr-2"
          draggable
          style={{
            touchAction: "none",
          }}
          onDragStart={(e) => {
            setIsDraggingSessionId(chat.id);
            e.dataTransfer.setData("text/plain", chat.id);
          }}
          onDragEnd={() => setIsDraggingSessionId(null)}
        >
          <ChatSessionDisplay
            chatSession={chat}
            isSelected={currentChatId === chat.id}
            showShareModal={showShareModal}
            showDeleteModal={showDeleteModal}
            closeSidebar={closeSidebar}
            isDragging={isDraggingSessionId === chat.id}
          />
        </div>
      );
    },
    [currentChatId, showShareModal, showDeleteModal, closeSidebar]
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

      if (active.id !== over?.id && folders) {
        const oldIndex = folders.findIndex(
          (f) => f.folder_id?.toString() === active.id
        );
        const newIndex = folders.findIndex(
          (f) => f.folder_id?.toString() === over?.id
        );

        if (oldIndex !== -1 && newIndex !== -1) {
          const newOrder = arrayMove(folders, oldIndex, newIndex);
          const displayPriorityMap = newOrder.reduce(
            (acc, folder, index) => {
              if (folder.folder_id !== undefined) {
                acc[folder.folder_id] = index;
              }
              return acc;
            },
            {} as Record<number, number>
          );

          updateFolderDisplayPriorities(displayPriorityMap);
          reorderFolders(displayPriorityMap);
        }
      }
    },
    [folders]
  );

  const numberOfGroups = Object.entries(groupedChatSesssions).length;
  const numberOfFolders = (folders ?? []).length;
  const numberOfGroupsAndFolders = numberOfGroups + numberOfFolders;
  const [expands, setExpands] = useState<boolean[]>(
    Array(numberOfGroupsAndFolders).fill(false)
  );
  const toggleExpanded = (index: number) => {
    const newExpands = Array.from(expands);
    newExpands[index] = !newExpands[index];
    setExpands(newExpands);
  };
  const expandAll = () => {
    setExpands(Array(numberOfGroupsAndFolders).fill(true));
  };
  const collapseAll = () => {
    setExpands(Array(numberOfGroupsAndFolders).fill(false));
  };

  return (
    <div className="flex flex-col gap-y-2 flex-grow">
      {popup}

      <Separator className="mb-0" />

      <SidebarProvider>
        <SidebarContent>
          <SidebarGroup className="gap-y-2">
            <div className="flex flex-row items-center">
              <SidebarGroupLabel className="opacity-50 flex flex-1 border-0 border-red-50">
                Chats
              </SidebarGroupLabel>
              <ToolTipHelper
                icon={<Search className="opacity-50" />}
                toolTipContent="Search through chats"
                onClick={toggleChatSessionSearchModal}
              />
              <ToolTipHelper
                icon={<FiPlus className="opacity-50" />}
                toolTipContent="Create new chat group"
                onClick={handleCreateFolder}
              />
              <ToolTipHelper
                icon={<ListTree className="opacity-50" />}
                toolTipContent="Collapse all folds"
                onClick={collapseAll}
              />
              <ToolTipHelper
                icon={<Expand className="opacity-50" />}
                toolTipContent="Expand all folds"
                onClick={expandAll}
              />
            </div>
            {isCreatingFolder && (
              <div className="py-2 px-2 flex flex-row justify-center items-center gap-x-4">
                <Input
                  placeholder="New Chat Group..."
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      handleNewFolderSubmit(e);
                    } else if (e.key === "Escape") {
                      setIsCreatingFolder(false);
                    }
                  }}
                  ref={newFolderInputRef}
                  type="text"
                  className="focus-visible:ring-1"
                />
                <div className="flex flex-row justify-center items-center gap-x-2">
                  <div onClick={handleNewFolderSubmit}>
                    <FiCheck size={14} />
                  </div>
                  <FiX size={14} onClick={() => setIsCreatingFolder(false)} />
                </div>
              </div>
            )}
            <DndContext
              modifiers={[restrictToVerticalAxis]}
              sensors={sensors}
              collisionDetection={closestCenter}
              onDragEnd={handleDragEnd}
            >
              <SortableContext
                items={(folders ?? []).map(
                  (folder) => folder.folder_id?.toString() ?? ""
                )}
                strategy={verticalListSortingStrategy}
              >
                {folders &&
                  folders
                    .sort(
                      (a, b) =>
                        (a.display_priority ?? 0) - (b.display_priority ?? 0)
                    )
                    .map((folder, index) => (
                      <SortableChatGroup
                        key={folder.folder_name}
                        name={folder.folder_name}
                        chatSessions={folder.chat_sessions}
                        expanded={expands[index]!}
                        toggleExpanded={() => toggleExpanded(index)}
                        selectedId={currentChatId}
                        editable
                        folderId={folder.folder_id!}
                        onEditFolder={handleEditFolder}
                        onDeleteFolder={handleDeleteFolder}
                      />
                    ))}
              </SortableContext>
            </DndContext>
            <div className="pt-2">
              <SidebarGroupLabel className="opacity-50 flex flex-1 border-0 border-red-50">
                History
              </SidebarGroupLabel>
            </div>
            {Object.entries(groupedChatSesssions).map(
              ([name, chats], index) => (
                <ChatGroup
                  key={name}
                  name={name}
                  chatSessions={chats}
                  expanded={expands[numberOfFolders + index]!}
                  toggleExpanded={() => toggleExpanded(numberOfFolders + index)}
                  selectedId={currentChatId}
                />
              )
            )}
          </SidebarGroup>
        </SidebarContent>
      </SidebarProvider>
    </div>
  );
}
