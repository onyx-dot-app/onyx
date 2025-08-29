"use client";

import React, { useMemo, useState } from "react";
import {
  Plus,
  Folder as FolderIcon,
  FileText,
  FolderOpen,
  FolderPlus,
} from "lucide-react";
import CreateProjectModal from "@/components/modals/CreateProjectModal";

type ProjectItem = {
  id: string;
  name: string;
  children?: ProjectItem[];
};

interface ProjectsProps {
  onCreateNewProject?: () => void;
  onOpenProject?: (projectId: string) => void;
}

function CollapsibleFolder({
  title,
  children,
  defaultOpen = true,
}: {
  title: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="w-full">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="w-full cursor-pointer text-base text-black dark:text-[#D4D4D4] hover:bg-background-chat-hover flex items-center gap-x-2 py-1 px-2 rounded-md"
      >
        {open ? (
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
        <span className="truncate">{title}</span>
      </button>

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

function LeafProject({
  item,
  onOpen,
}: {
  item: ProjectItem;
  onOpen?: (id: string) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onOpen?.(item.id)}
      className="w-full text-left text-base text-black dark:text-[#D4D4D4] hover:bg-background-chat-hover flex items-center gap-x-2 py-1 px-2 rounded-md"
    >
      <FileText
        size={16}
        className="flex-none text-text-history-sidebar-button"
      />
      <span className="truncate">{item.name}</span>
    </button>
  );
}

export default function Projects({
  onCreateNewProject,
  onOpenProject,
}: ProjectsProps) {
  const [isCreateProjectOpen, setIsCreateProjectOpen] = useState(false);
  const data = useMemo<ProjectItem[]>(
    () => [
      {
        id: "folder-notes",
        name: "_Notes",
        children: [
          { id: "p-1", name: "Notes app UI code" },
          { id: "p-2", name: "Classy notes app UI" },
          { id: "p-3", name: "Notes app feature plan" },
          { id: "p-4", name: "UI design prototype" },
          { id: "p-5", name: "Notes app feature list" },
        ],
      },
      { id: "folder-1", name: "Sri Sneka", children: [] },
      { id: "folder-2", name: "Understanding Vespa", children: [] },
      { id: "folder-3", name: "Kubernetes", children: [] },
    ],
    []
  );

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
        {data.map((item) =>
          item.children && item.children.length > 0 ? (
            <CollapsibleFolder key={item.id} title={item.name} defaultOpen>
              {item.children.map((c) => (
                <LeafProject key={c.id} item={c} onOpen={onOpenProject} />
              ))}
            </CollapsibleFolder>
          ) : (
            <div key={item.id} className="w-full">
              <button
                type="button"
                onClick={() => onOpenProject?.(item.id)}
                className="w-full cursor-pointer text-base text-black dark:text-[#D4D4D4] hover:bg-background-chat-hover flex items-center gap-x-2 py-1 px-2 rounded-md"
              >
                <FolderIcon
                  size={18}
                  className="flex-none text-text-history-sidebar-button"
                />
                <span className="truncate">{item.name}</span>
              </button>
            </div>
          )
        )}
      </div>
      <CreateProjectModal
        open={isCreateProjectOpen}
        setOpen={setIsCreateProjectOpen}
        onCreate={async (_name) => {
          // TODO: hook into real project creation when API is ready.
          onCreateNewProject?.();
        }}
      />
    </div>
  );
}
