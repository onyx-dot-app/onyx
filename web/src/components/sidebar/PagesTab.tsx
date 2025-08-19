import { ChatSession } from "@/app/chat/interfaces";
import {
  createFolder,
  updateFolderName,
  deleteFolder,
  addChatToFolder,
  updateFolderDisplayPriorities,
} from "@/app/chat/folders/FolderManagement";
import { Folder } from "@/app/chat/folders/interfaces";
import { usePopup } from "@/components/admin/connectors/Popup";
import { useRouter } from "next/navigation";
import { FiPlus, FiCheck, FiX } from "react-icons/fi";
import { FolderDropdown } from "@/app/chat/folders/FolderDropdown";
import { ChatSessionDisplay } from "./ChatSessionDisplay";
import { useState, useCallback, useRef, useContext, useEffect } from "react";
import { Caret } from "@/components/icons/icons";
import { groupSessionsByDateRange } from "@/app/chat/lib";
import React from "react";
import {
  Tooltip,
  TooltipProvider,
  TooltipTrigger,
  TooltipContent,
} from "@/components/ui/tooltip";
import { Search } from "lucide-react";
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

interface SortableFolderProps {
  folder: Folder;
  children: React.ReactNode;
  currentChatId?: string;
  showShareModal?: (chatSession: ChatSession) => void;
  showDeleteModal?: (chatSession: ChatSession) => void;
  closeSidebar?: () => void;
  onEdit: (folderId: number, newName: string) => void;
  onDelete: (folderId: number) => void;
  onDrop: (folderId: number, chatSessionId: string) => void;
  index: number;
}

const SortableFolder: React.FC<SortableFolderProps> = (props) => {
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
    id: props.folder.folder_id?.toString() ?? "",
    disabled: mobile,
  });
  const ref = useRef<HTMLDivElement>(null);

  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    zIndex: isDragging ? 1000 : "auto",
    position: isDragging ? "relative" : "static",
    opacity: isDragging ? 0.6 : 1,
  };

  useEffect(() => {
    setIsDragging(isDraggingDndKit);
  }, [isDraggingDndKit]);

  return (
    <div
      ref={setNodeRef}
      className="pr-3 ml-4 overflow-visible flex items-start"
      style={style}
      {...attributes}
    >
      <FolderDropdown {...listeners} ref={ref} {...props} />
    </div>
  );
};

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
    [router, setPopup, refreshChatSessions, refreshFolders]
  );

  const handleDeleteFolder = useCallback(
    (folderId: number) => {
      if (
        confirm(
          "Are you sure you want to delete this folder? This action cannot be undone."
        )
      ) {
        deleteFolder(folderId)
          .then(() => {
            router.refresh();
            setPopup({
              message: "Folder deleted successfully",
              type: "success",
            });
          })
          .catch((error: Error) => {
            console.error("Failed to delete folder:", error);
            setPopup({
              message: `Failed to delete folder: ${error.message}`,
              type: "error",
            });
          });
      }
    },
    [router, setPopup]
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

  const isHistoryEmpty = !existingChats || existingChats.length === 0;

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

  return (
    <div className="flex flex-col gap-y-2 flex-grow">
      {popup}
      <div className="px-4 mt-2 group mr-2 bg-background-sidebar dark:bg-transparent z-20">
        <div className="flex  group justify-between text-sm gap-x-2 text-text-300/80 items-center font-normal leading-normal">
          <p>Chats</p>

          <TooltipProvider delayDuration={1000}>
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  className="my-auto mr-auto  group-hover:opacity-100 opacity-0 transition duration-200 cursor-pointer gap-x-1 items-center text-black text-xs font-medium leading-normal mobile:hidden"
                  onClick={() => {
                    toggleChatSessionSearchModal?.();
                  }}
                >
                  <Search
                    className="flex-none text-text-mobile-sidebar"
                    size={12}
                  />
                </button>
              </TooltipTrigger>
              <TooltipContent>Search Chats</TooltipContent>
            </Tooltip>
          </TooltipProvider>

          <button
            onClick={handleCreateFolder}
            className="flex group-hover:opacity-100 opacity-0 transition duration-200 cursor-pointer gap-x-1 items-center text-black text-xs font-medium leading-normal"
          >
            <FiPlus size={12} className="flex-none" />
            Create Group
          </button>
        </div>
      </div>

      {isCreatingFolder ? (
        <div className="px-4">
          <div className="flex  overflow-visible items-center w-full text-text-500 rounded-md p-1 relative">
            <Caret size={16} className="flex-none mr-1" />
            <input
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  handleNewFolderSubmit(e);
                }
              }}
              ref={newFolderInputRef}
              type="text"
              placeholder="Enter group name"
              className="text-sm font-medium bg-transparent outline-none w-full pb-1 border-b border-background-500 transition-colors duration-200"
            />
            <div className="flex -my-1">
              <div
                onClick={handleNewFolderSubmit}
                className="cursor-pointer px-1"
              >
                <FiCheck size={14} />
              </div>
              <div
                onClick={() => setIsCreatingFolder(false)}
                className="cursor-pointer px-1"
              >
                <FiX size={14} />
              </div>
            </div>
          </div>
        </div>
      ) : (
        <></>
      )}

      {folders && folders.length > 0 && (
        <DndContext
          modifiers={[restrictToVerticalAxis]}
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragEnd={handleDragEnd}
        >
          <SortableContext
            items={folders.map((f) => f.folder_id?.toString() ?? "")}
            strategy={verticalListSortingStrategy}
          >
            <div className="space-y-2">
              {folders
                .sort(
                  (a, b) =>
                    (a.display_priority ?? 0) - (b.display_priority ?? 0)
                )
                .map((folder, index) => (
                  <SortableFolder
                    key={folder.folder_id}
                    folder={folder}
                    currentChatId={currentChatId}
                    showShareModal={showShareModal}
                    showDeleteModal={showDeleteModal}
                    closeSidebar={closeSidebar}
                    onEdit={handleEditFolder}
                    onDelete={handleDeleteFolder}
                    onDrop={handleDrop}
                    index={index}
                  >
                    {folder.chat_sessions &&
                      folder.chat_sessions.map((chat) =>
                        renderChatSession(
                          chat,
                          folders != undefined && folders.length > 0
                        )
                      )}
                  </SortableFolder>
                ))}
            </div>
          </SortableContext>
        </DndContext>
      )}

      <div className="pl-4 pr-3">
        {!isHistoryEmpty && (
          <>
            {Object.entries(groupedChatSesssions)
              .filter(([groupName, chats]) => chats.length > 0)
              .map(([groupName, chats], index) => (
                <FolderDropdown
                  key={groupName}
                  folder={{
                    folder_name: groupName,
                    chat_sessions: chats,
                    display_priority: 0,
                  }}
                  currentChatId={currentChatId}
                  showShareModal={showShareModal}
                  closeSidebar={closeSidebar}
                  onEdit={handleEditFolder}
                  onDrop={handleDrop}
                  index={folders ? folders.length + index : index}
                >
                  {chats.map((chat) =>
                    renderChatSession(
                      chat,
                      folders != undefined && folders.length > 0
                    )
                  )}
                </FolderDropdown>
              ))}
          </>
        )}

        {isHistoryEmpty && (!folders || folders.length === 0) && (
          <p className="text-sm max-w-full mt-2 w-[250px]">
            Try sending a message! Your chat history will appear here.
          </p>
        )}
      </div>
    </div>
  );
}
