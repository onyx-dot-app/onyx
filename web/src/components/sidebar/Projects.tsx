"use client";

import React, { useMemo, useState, useEffect } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  Plus,
  Folder as FolderIcon,
  FileText,
  FolderOpen,
  FolderPlus,
  Pencil,
  Trash2,
  Check,
  X,
} from "lucide-react";
import CreateProjectModal from "@/components/modals/CreateProjectModal";
import { DeleteEntityModal } from "@/components/DeleteEntityModal";
import { useProjectsContext } from "@/app/chat/projects/ProjectsContext";
import type { ChatSession } from "@/app/chat/interfaces";
import { ChatSessionDisplay } from "./ChatSessionDisplay";
import {
  Tooltip,
  TooltipProvider,
  TooltipTrigger,
  TooltipContent,
} from "@/components/ui/tooltip";

interface ProjectsProps {
  onOpenProject?: (projectId: string) => void;
}

function CollapsibleFolder({
  title,
  children,
  defaultOpen = true,
  onToggle,
  onNameClick,
  onRename,
  onDeleteClick,
  isSelected,
}: {
  title: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
  onToggle?: (open: boolean) => void;
  onNameClick?: () => void;
  onRename?: (newName: string) => Promise<void> | void;
  onDeleteClick?: () => void;
  isSelected?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [hoveringIcon, setHoveringIcon] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [editValue, setEditValue] = useState(title);
  const [isSaving, setIsSaving] = useState(false);
  return (
    <div className="w-full">
      <div
        className={`w-full group flex items-center gap-x-1 px-1 rounded-md hover:bg-background-chat-hover ${isSelected ? "bg-background-chat-selected" : ""}`}
      >
        <button
          type="button"
          aria-expanded={open}
          onClick={() =>
            setOpen((v) => {
              const next = !v;
              onToggle?.(next);
              return next;
            })
          }
          onMouseEnter={() => setHoveringIcon(true)}
          onMouseLeave={() => setHoveringIcon(false)}
          className="cursor-pointer text-base rounded-md p-1"
        >
          {open || hoveringIcon ? (
            <FolderOpen
              size={18}
              className="flex-none text-text-history-sidebar-button"
            />
          ) : (
            <FolderIcon
              size={18}
              className="flex-none text-text-history-sidebar-button"
            />
          )}
        </button>
        {isEditing ? (
          <input
            className="w-full text-base bg-transparent outline-none text-black dark:text-[#D4D4D4] py-1 rounded-md border-b border-transparent focus:border-accent-background-hovered"
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            onKeyDown={async (e) => {
              if (e.key === "Enter") {
                if (!onRename) return;
                const nextName = editValue.trim();
                if (!nextName || nextName === title) {
                  setIsEditing(false);
                  setEditValue(title);
                  return;
                }
                try {
                  setIsSaving(true);
                  await onRename(nextName);
                } finally {
                  setIsSaving(false);
                  setIsEditing(false);
                }
              } else if (e.key === "Escape") {
                setIsEditing(false);
                setEditValue(title);
              }
            }}
            autoFocus
          />
        ) : (
          <button
            type="button"
            onClick={() => {
              setOpen((v) => {
                const next = !v;
                onToggle?.(next);
                return next;
              });
              onNameClick?.();
            }}
            className="w-full text-left text-base text-black dark:text-[#D4D4D4] py-1  rounded-md"
          >
            <span className="truncate">{title}</span>
          </button>
        )}
        <div
          className={`ml-2 flex items-center gap-x-1 transition-opacity ${isEditing ? "opacity-100" : "opacity-0 group-hover:opacity-100"}`}
        >
          {isEditing ? (
            <>
              <button
                type="button"
                aria-label="Save name"
                disabled={isSaving}
                onClick={async (e) => {
                  e.stopPropagation();
                  if (!onRename) return;
                  const nextName = editValue.trim();
                  if (!nextName || nextName === title) {
                    setIsEditing(false);
                    setEditValue(title);
                    return;
                  }
                  try {
                    setIsSaving(true);
                    await onRename(nextName);
                  } finally {
                    setIsSaving(false);
                    setIsEditing(false);
                  }
                }}
                className="p-1 rounded hover:bg-accent-background-hovered text-green-600 disabled:opacity-50"
              >
                <Check size={16} />
              </button>
              <button
                type="button"
                aria-label="Cancel rename"
                onClick={(e) => {
                  e.stopPropagation();
                  setIsEditing(false);
                  setEditValue(title);
                }}
                className="p-1 rounded hover:bg-accent-background-hovered text-red-600"
              >
                <X size={16} />
              </button>
            </>
          ) : (
            <>
              <button
                type="button"
                aria-label="Rename project"
                onClick={(e) => {
                  e.stopPropagation();
                  setIsEditing(true);
                  setEditValue(title);
                }}
                className="p-1 rounded hover:bg-accent-background-hovered text-text-history-sidebar-button"
              >
                <Pencil size={16} />
              </button>
              {onDeleteClick && (
                <button
                  type="button"
                  aria-label="Delete project"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDeleteClick();
                  }}
                  className="p-1 rounded hover:bg-accent-background-hovered text-text-history-sidebar-button"
                >
                  <Trash2 size={16} />
                </button>
              )}
            </>
          )}
        </div>
      </div>

      <div
        className={`grid transition-[grid-template-rows,opacity] duration-300 ease-out ${
          open ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0"
        }`}
      >
        <div className="overflow-hidden">
          <div className="pl-6 pr-2 py-1 space-y-1">{children}</div>
        </div>
      </div>
    </div>
  );
}

export default function Projects({ onOpenProject }: ProjectsProps) {
  const [isCreateProjectOpen, setIsCreateProjectOpen] = useState(false);
  const {
    createProject,
    projects,
    currentProjectId,
    currentProjectDetails,
    renameProject,
    deleteProject,
  } = useProjectsContext();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const chatSessionId = searchParams?.get("chatId");
  const [deleteTarget, setDeleteTarget] = useState<{
    id: number;
    name: string;
  } | null>(null);
  return (
    <div className="flex flex-col">
      <div className="group flex justify-between px-4 ">
        <p className="my-auto font-normal text-sm leading-normal text-text-500/80 dark:text-[#D4D4D4]">
          Projects
        </p>
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                aria-label="Create project"
                onClick={() => setIsCreateProjectOpen(true)}
                className="p-1.5 group-hover:opacity-100 opacity-0 transition duration-200 cursor-pointer hover:bg-accent-background-hovered rounded-md"
              >
                <FolderPlus size={18} />
              </button>
            </TooltipTrigger>
            <TooltipContent>Create Project</TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </div>

      <div className="px-2 gap-y-1 flex flex-col text-text-history-sidebar-button items-center">
        {projects.map((p) => (
          <CollapsibleFolder
            key={p.id}
            title={p.name}
            defaultOpen={false}
            isSelected={p.id == currentProjectId}
            onNameClick={() => {
              const params = new URLSearchParams(
                searchParams?.toString() || ""
              );
              // Set the new project ID and remove any assistant selection
              params.set("projectid", String(p.id));
              if (params.has("assistantId")) {
                params.delete("assistantId");
              }
              if (params.has("chatId")) {
                params.delete("chatId");
              }
              router.push(`${pathname}?${params.toString()}`);
            }}
            onRename={async (newName: string) => {
              await renameProject(p.id, newName);
            }}
            onDeleteClick={() => {
              setDeleteTarget({ id: p.id, name: p.name });
            }}
          >
            {p.chat_sessions && p.chat_sessions.length > 0 ? (
              p.chat_sessions.map((chatSession) => (
                <ChatSessionDisplay
                  key={chatSession.id}
                  chatSession={chatSession}
                  isSelected={chatSession.id == chatSessionId}
                  showDragHandle={false}
                  projectId={p.id}
                  isCustomAssistant={
                    currentProjectId === p.id &&
                    !!currentProjectDetails?.persona_id_to_is_default &&
                    currentProjectDetails.persona_id_to_is_default[
                      chatSession.persona_id
                    ] === false
                  }
                />
              ))
            ) : (
              <div className="text-xs text-neutral-500 px-2 py-1">
                This project doesn’t have any chat sessions yet.
              </div>
            )}
          </CollapsibleFolder>
        ))}
        {projects.length === 0 && (
          <p className="text-xs text-neutral-500 px-2">No projects yet.</p>
        )}
      </div>
      <CreateProjectModal
        open={isCreateProjectOpen}
        setOpen={setIsCreateProjectOpen}
        onCreate={async (_name) => {
          await createProject(_name);
        }}
      />
      <DeleteEntityModal
        isOpen={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        onConfirm={async () => {
          if (!deleteTarget) return;
          const targetId = deleteTarget.id;
          await deleteProject(targetId);
          setDeleteTarget(null);
          const params = new URLSearchParams(searchParams?.toString() || "");
          if (params.get("projectid") === String(targetId)) {
            params.delete("projectid");
            if (params.has("chatId")) params.delete("chatId");
            router.push(`${pathname}?${params.toString()}`);
          }
        }}
        entityType="folder"
        entityName={deleteTarget?.name || ""}
      />
    </div>
  );
}
