"use client";

import React, { useState, useMemo, useCallback } from "react";
import { useRouter } from "next/navigation";
import type { Route } from "next";
import CommandMenu from "@/refresh-components/commandmenu/CommandMenu";
import useChatSessions from "@/hooks/useChatSessions";
import { useProjects } from "@/lib/hooks/useProjects";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import CreateProjectModal from "@/components/modals/CreateProjectModal";
import { formatDisplayTime } from "@/sections/sidebar/chatSearchUtils";
import { useSettingsContext } from "@/components/settings/SettingsProvider";
import { useCurrentAgent } from "@/hooks/useAgents";
import { UNNAMED_CHAT } from "@/lib/constants";
import Text from "@/refresh-components/texts/Text";
import {
  SvgEditBig,
  SvgFolder,
  SvgFolderPlus,
  SvgFileText,
  SvgBubbleText,
} from "@opal/icons";

interface ChatSearchCommandMenuProps {
  trigger: React.ReactNode;
}

interface FilterableChat {
  id: string;
  label: string;
  time: string;
}

interface FilterableProject {
  id: number;
  label: string;
  description: string | null;
  time: string;
}

export default function ChatSearchCommandMenu({
  trigger,
}: ChatSearchCommandMenuProps) {
  const [open, setOpen] = useState(false);
  const [searchValue, setSearchValue] = useState("");
  const [activeFilter, setActiveFilter] = useState<
    "all" | "chats" | "projects"
  >("all");
  const router = useRouter();

  // Data hooks
  const { chatSessions } = useChatSessions();
  const { projects } = useProjects();
  const combinedSettings = useSettingsContext();
  const currentAgent = useCurrentAgent();
  const createProjectModal = useCreateModal();

  // Constants for preview limits
  const PREVIEW_CHATS_LIMIT = 4;
  const PREVIEW_PROJECTS_LIMIT = 2;

  // Transform and filter chat sessions (sorted by latest first)
  const filteredChats = useMemo<FilterableChat[]>(() => {
    const chats = chatSessions
      .map((session) => ({
        id: session.id,
        label: session.name || UNNAMED_CHAT,
        time: session.time_updated || session.time_created,
      }))
      .sort((a, b) => new Date(b.time).getTime() - new Date(a.time).getTime());

    if (!searchValue.trim()) return chats;

    const term = searchValue.toLowerCase();
    return chats.filter((chat) => chat.label.toLowerCase().includes(term));
  }, [chatSessions, searchValue]);

  // Transform and filter projects (sorted by latest first)
  const filteredProjects = useMemo<FilterableProject[]>(() => {
    const projectList = projects
      .map((project) => ({
        id: project.id,
        label: project.name,
        description: project.description,
        time: project.created_at,
      }))
      .sort((a, b) => new Date(b.time).getTime() - new Date(a.time).getTime());

    if (!searchValue.trim()) return projectList;

    const term = searchValue.toLowerCase();
    return projectList.filter(
      (project) =>
        project.label.toLowerCase().includes(term) ||
        project.description?.toLowerCase().includes(term)
    );
  }, [projects, searchValue]);

  // Compute displayed items based on filter state
  const displayedChats = useMemo(() => {
    if (activeFilter === "all" && !searchValue.trim()) {
      return filteredChats.slice(0, PREVIEW_CHATS_LIMIT);
    }
    return filteredChats;
  }, [filteredChats, activeFilter, searchValue]);

  const displayedProjects = useMemo(() => {
    if (activeFilter === "all" && !searchValue.trim()) {
      return filteredProjects.slice(0, PREVIEW_PROJECTS_LIMIT);
    }
    return filteredProjects;
  }, [filteredProjects, activeFilter, searchValue]);

  // Header filters for showing active filter as a chip
  const headerFilters = useMemo(() => {
    if (activeFilter === "chats") {
      return [{ id: "chats", label: "Recent Sessions", icon: SvgFileText }];
    }
    if (activeFilter === "projects") {
      return [{ id: "projects", label: "Projects", icon: SvgFolder }];
    }
    return [];
  }, [activeFilter]);

  const handleFilterRemove = useCallback(() => {
    setActiveFilter("all");
  }, []);

  // Navigation handlers
  const handleNewSession = useCallback(() => {
    const href =
      combinedSettings?.settings?.disable_default_assistant && currentAgent
        ? `/chat?assistantId=${currentAgent.id}`
        : "/chat";
    router.push(href as Route);
    setOpen(false);
  }, [router, combinedSettings, currentAgent]);

  const handleChatSelect = useCallback(
    (chatId: string) => {
      router.push(`/chat?chatId=${chatId}` as Route);
      setOpen(false);
    },
    [router]
  );

  const handleProjectSelect = useCallback(
    (projectId: number) => {
      router.push(`/chat?projectId=${projectId}` as Route);
      setOpen(false);
    },
    [router]
  );

  const handleNewProject = useCallback(() => {
    setOpen(false);
    createProjectModal.toggle(true);
  }, [createProjectModal]);

  const handleOpenChange = useCallback((newOpen: boolean) => {
    setOpen(newOpen);
    if (!newOpen) {
      setSearchValue("");
      setActiveFilter("all");
    }
  }, []);

  const hasResults = displayedChats.length > 0 || displayedProjects.length > 0;
  const hasSearchValue = searchValue.trim().length > 0;

  return (
    <>
      <div onClick={() => setOpen(true)}>{trigger}</div>

      <CommandMenu open={open} onOpenChange={handleOpenChange}>
        <CommandMenu.Content>
          <CommandMenu.Header
            placeholder="Search chat sessions, projects..."
            value={searchValue}
            onValueChange={setSearchValue}
            filters={headerFilters}
            onFilterRemove={handleFilterRemove}
            onClose={() => setOpen(false)}
          />

          <CommandMenu.List
            emptyMessage={
              hasSearchValue ? "No results found" : "No chats or projects yet"
            }
          >
            {/* New Session action - always shown when no search and no filter */}
            {!hasSearchValue && activeFilter === "all" && (
              <CommandMenu.Action
                value="new-session"
                icon={SvgEditBig}
                onSelect={handleNewSession}
              >
                New Session
              </CommandMenu.Action>
            )}

            {/* Recent Sessions section - show if filter is 'all' or 'chats' */}
            {(activeFilter === "all" || activeFilter === "chats") &&
              displayedChats.length > 0 && (
                <>
                  {activeFilter === "all" && (
                    <CommandMenu.Filter
                      value="recent-sessions"
                      onSelect={() => setActiveFilter("chats")}
                    >
                      Recent Sessions
                    </CommandMenu.Filter>
                  )}
                  {displayedChats.map((chat) => (
                    <CommandMenu.Item
                      key={chat.id}
                      value={`chat-${chat.id}`}
                      icon={SvgBubbleText}
                      rightContent={
                        <Text secondaryBody text03>
                          {formatDisplayTime(chat.time)}
                        </Text>
                      }
                      onSelect={() => handleChatSelect(chat.id)}
                    >
                      {chat.label}
                    </CommandMenu.Item>
                  ))}
                </>
              )}

            {/* Projects section - show if filter is 'all' or 'projects' */}
            {(activeFilter === "all" || activeFilter === "projects") &&
              displayedProjects.length > 0 && (
                <>
                  {activeFilter === "all" && (
                    <CommandMenu.Filter
                      value="projects"
                      onSelect={() => setActiveFilter("projects")}
                    >
                      Projects
                    </CommandMenu.Filter>
                  )}
                  {displayedProjects.map((project) => (
                    <CommandMenu.Item
                      key={project.id}
                      value={`project-${project.id}`}
                      icon={SvgFolder}
                      rightContent={
                        <Text secondaryBody text03>
                          {formatDisplayTime(project.time)}
                        </Text>
                      }
                      onSelect={() => handleProjectSelect(project.id)}
                    >
                      {project.label}
                    </CommandMenu.Item>
                  ))}
                </>
              )}

            {/* New Project action - shown when no search and no filter or projects filter */}
            {!hasSearchValue &&
              (activeFilter === "all" || activeFilter === "projects") && (
                <CommandMenu.Action
                  value="new-project"
                  icon={SvgFolderPlus}
                  onSelect={handleNewProject}
                >
                  New Project
                </CommandMenu.Action>
              )}
          </CommandMenu.List>
        </CommandMenu.Content>
      </CommandMenu>

      {/* Project creation modal */}
      <createProjectModal.Provider>
        <CreateProjectModal />
      </createProjectModal.Provider>
    </>
  );
}
