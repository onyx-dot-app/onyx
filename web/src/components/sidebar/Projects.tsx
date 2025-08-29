"use client";

import React, { useMemo, useState, useEffect } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  Plus,
  Folder as FolderIcon,
  FileText,
  FolderOpen,
  FolderPlus,
} from "lucide-react";
import CreateProjectModal from "@/components/modals/CreateProjectModal";
import { useProjectsContext } from "@/app/chat/projects/ProjectsContext";
import type { ChatSession } from "@/app/chat/interfaces";

type ProjectItem = {
  id: string;
  name: string;
  children?: ProjectItem[];
};

interface ProjectsProps {
  onOpenProject?: (projectId: string) => void;
}

function CollapsibleFolder({
  title,
  children,
  defaultOpen = true,
  onToggle,
  onNameClick,
}: {
  title: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
  onToggle?: (open: boolean) => void;
  onNameClick?: () => void;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [hoveringIcon, setHoveringIcon] = useState(false);

  return (
    <div className="w-full">
      <div className="w-full flex items-center gap-x-2 px-2 rounded-md hover:bg-background-chat-hover">
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
        <button
          type="button"
          onClick={onNameClick}
          className="w-full text-left text-base text-black dark:text-[#D4D4D4] py-1 px-2 rounded-md"
        >
          <span className="truncate">{title}</span>
        </button>
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
  const { createProject, projects } = useProjectsContext();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  return (
    <div className="flex flex-col gap-y-2 mt-4">
      <div className="px-4 -mx-2 gap-y-1 flex flex-col text-text-history-sidebar-button gap-x-1.5 items-center">
        <button
          type="button"
          onClick={() => setIsCreateProjectOpen(true)}
          className="w-full px-2 py-1 group rounded-md items-center hover:bg-accent-background-hovered cursor-pointer transition-all duration-150 flex justify-between"
        >
          <p className="my-auto flex font-normal items-center">New project</p>
          <FolderPlus size={20} />
        </button>
      </div>

      <div className="px-4 space-y-1">
        {projects.map((p) => (
          <CollapsibleFolder
            key={p.id}
            title={p.name}
            defaultOpen={false}
            onNameClick={() => {
              const params = new URLSearchParams(
                searchParams?.toString() || ""
              );
              params.set("projectid", String(p.id));
              router.push(`${pathname}?${params.toString()}`);
            }}
          >
            <div className="text-xs text-neutral-500 px-2 py-1">
              This project doesn’t have any chats.
            </div>
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
    </div>
  );
}
