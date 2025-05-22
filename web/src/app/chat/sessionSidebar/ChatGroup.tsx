import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
} from "@/components/ui/sidebar";
import { ChatSession } from "../interfaces";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { ChevronRight } from "lucide-react";
import { ChatSessionDisplay } from "./ChatSessionDisplay";
import { useCallback, useEffect, useRef, useState } from "react";
import { FiEdit2, FiMoreHorizontal, FiTrash } from "react-icons/fi";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { DefaultDropdownElement } from "@/components/Dropdown";
import { Input } from "@/components/ui/input";
import Text from "@/components/ui/text";
import { Button } from "@/components/ui/button";

export interface ChatGroupProps {
  name: string;
  chatSessions: ChatSession[];
  expanded: boolean;
  toggleExpanded: () => void;
  selectedId: string | undefined;
  editable?: boolean;
  folderId?: number;
  onEditFolder?: (folderId: number, newName: string) => void;
  onDeleteFolder?: (folderId: number) => void;
}

export default function ChatGroup({
  name,
  chatSessions,
  expanded,
  toggleExpanded,
  selectedId,
  editable = false,
  folderId,
  onEditFolder,
  onDeleteFolder,
}: ChatGroupProps) {
  const hasChatsToShow = chatSessions.length > 0;
  const [hover, setHover] = useState(false);
  const [editingFolder, setEditingFolder] = useState(false);
  const [deletingFolder, setDeletingFolder] = useState(false);

  const reset = () => {
    setDeletingFolder(false);
    setEditingFolder(false);
    setHover(false);
  };

  const folderRenameRef = useRef<HTMLInputElement>(null);

  const handleFolderRename = useCallback(
    async (e: React.FormEvent<HTMLDivElement>) => {
      e.preventDefault();
      const newFolderName = folderRenameRef.current?.value;
      if (newFolderName && folderId && onEditFolder) {
        onEditFolder(folderId, newFolderName);
      }
      reset();
    },
    []
  );

  useEffect(() => {
    document.addEventListener("mousedown", (e) => {
      if (
        folderRenameRef.current &&
        !folderRenameRef.current.contains(e.target as Node) &&
        editingFolder
      ) {
        reset();
      }
    });
  }, [editingFolder, reset]);

  return (
    <SidebarMenu>
      <Collapsible
        className="group/collapsible"
        open={hasChatsToShow && expanded}
      >
        <CollapsibleTrigger
          asChild
          onClick={toggleExpanded}
          onMouseEnter={() => setHover(true)}
          onMouseLeave={() => {
            setHover(false);
            setDeletingFolder(false);
          }}
        >
          <SidebarMenuButton
            tooltip={name}
            className={`flex flex-row ${editingFolder ? "h-fit" : ""}`}
          >
            {editingFolder ? (
              <Input
                placeholder="New Folder Name..."
                className="flex focus-visible:ring-1"
                ref={folderRenameRef}
                defaultValue={name}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    handleFolderRename(e);
                  } else if (e.key === "Escape") {
                    reset();
                  }
                }}
              />
            ) : (
              <span className="flex flex-1">{name}</span>
            )}
            {editable && hover && !editingFolder && (
              <Popover>
                <PopoverTrigger asChild>
                  <FiMoreHorizontal size={16} />
                </PopoverTrigger>
                <PopoverContent
                  className={`p-0 ${
                    deletingFolder ? "w-[250px]" : "w-[150px]"
                  }`}
                >
                  {deletingFolder ? (
                    <div className="p-4 flex flex-col gap-y-4">
                      <Text>Are you sure you want to delete this folder?</Text>
                      <div className="px-2 flex flex-1 flex-row justify-center gap-x-2">
                        <Button
                          variant="destructive"
                          onClick={() => {
                            if (folderId && onDeleteFolder) {
                              onDeleteFolder(folderId);
                            }
                            reset();
                          }}
                        >
                          Delete
                        </Button>
                        <Button onClick={reset}>Cancel</Button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <DefaultDropdownElement
                        name="Rename"
                        icon={FiEdit2}
                        onSelect={() => {
                          setEditingFolder(true);
                          setTimeout(() => {
                            folderRenameRef.current?.focus();
                          }, 0);
                        }}
                      />
                      <DefaultDropdownElement
                        name="Delete"
                        icon={FiTrash}
                        onSelect={() => setDeletingFolder(true)}
                      />
                    </>
                  )}
                </PopoverContent>
              </Popover>
            )}
            <ChevronRight
              className={`ml-auto transition-transform duration-200 group-data-[state=open]/collapsible:rotate-90 ${
                hasChatsToShow ? "" : "opacity-25"
              }`}
            />
          </SidebarMenuButton>
        </CollapsibleTrigger>

        <CollapsibleContent>
          <SidebarMenuSub>
            {chatSessions.map((chatSession) => (
              <SidebarMenuSubItem key={chatSession.name}>
                <SidebarMenuSubButton asChild>
                  <ChatSessionDisplay
                    chatSession={chatSession}
                    isSelected={selectedId === chatSession.id}
                  />
                </SidebarMenuSubButton>
              </SidebarMenuSubItem>
            ))}
          </SidebarMenuSub>
        </CollapsibleContent>
      </Collapsible>
    </SidebarMenu>
  );
}
