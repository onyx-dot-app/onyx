"use client";

import React, { useState, useMemo, useCallback } from "react";
import { useRouter } from "next/navigation";
import type { Route } from "next";
import CommandMenu, {
  useCommandMenuContext,
} from "@/refresh-components/commandmenu/CommandMenu";
import { useProjects } from "@/lib/hooks/useProjects";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import CreateProjectModal from "@/components/modals/CreateProjectModal";
import { formatDisplayTime } from "@/sections/sidebar/chatSearchUtils";
import { useSettingsContext } from "@/providers/SettingsProvider";
import { useCurrentAgent } from "@/hooks/useAgents";
import Text from "@/refresh-components/texts/Text";
import {
  useChatSearchOptimistic,
  FilterableChat,
} from "./useChatSearchOptimistic";
import {
  SvgEditBig,
  SvgFolder,
  SvgFolderPlus,
  SvgBubbleText,
  SvgArrowUpDown,
  SvgKeystroke,
} from "@opal/icons";

/**
 * Dynamic footer that shows contextual action labels based on highlighted item type
 */
function DynamicFooter() {
  const { highlightedItemType } = useCommandMenuContext();

  // "Show all" for filters, "Open" for everything else (items, actions, or no highlight)
  const actionLabel = highlightedItemType === "filter" ? "Show all" : "Open";

  return (
    <CommandMenu.Footer
      leftActions={
        <>
          <CommandMenu.FooterAction icon={SvgArrowUpDown} label="Select" />
          <CommandMenu.FooterAction icon={SvgKeystroke} label={actionLabel} />
        </>
      }
    />
  );
}

interface ChatSearchCommandMenuProps {
  trigger: React.ReactNode;
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
  const { projects } = useProjects();
  const combinedSettings = useSettingsContext();
  const currentAgent = useCurrentAgent();
  const createProjectModal = useCreateModal();

  // Constants for preview limits
  const PREVIEW_CHATS_LIMIT = 4;
  const PREVIEW_PROJECTS_LIMIT = 2;

  // Determine if we should enable optimistic search (when searching or viewing chats filter)
  const shouldUseOptimisticSearch =
    searchValue.trim().length > 0 || activeFilter === "chats";

  // Use optimistic search hook for chat sessions (includes fallback from useChatSessions + useProjects)
  const {
    results: filteredChats,
    isSearching,
    hasMore,
    isLoadingMore,
    sentinelRef,
  } = useChatSearchOptimistic({
    searchQuery: searchValue,
    enabled: shouldUseOptimisticSearch,
  });

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
      return [{ id: "chats", label: "Sessions" }];
    }
    if (activeFilter === "projects") {
      return [{ id: "projects", label: "Projects" }];
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
        ? `/app?assistantId=${currentAgent.id}`
        : "/app";
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
                  {searchValue.trim().length === 0 && (
                    <CommandMenu.Filter
                      value="recent-sessions"
                      onSelect={() => setActiveFilter("chats")}
                      isApplied={activeFilter === "chats"}
                    >
                      {activeFilter === "chats" ? "Recent" : "Recent Sessions"}
                    </CommandMenu.Filter>
                  )}
                  {displayedChats.map((chat) => (
                    <CommandMenu.Item
                      key={chat.id}
                      value={`chat-${chat.id}`}
                      icon={SvgBubbleText}
                      rightContent={({ isHighlighted }) =>
                        isHighlighted ? (
                          <Text figureKeystroke text02>
                            ↵
                          </Text>
                        ) : (
                          <Text secondaryBody text03>
                            {formatDisplayTime(chat.time)}
                          </Text>
                        )
                      }
                      onSelect={() => handleChatSelect(chat.id)}
                    >
                      {chat.label}
                    </CommandMenu.Item>
                  ))}
                  {/* Infinite scroll sentinel and loading indicator for chats */}
                  {activeFilter === "chats" && hasMore && (
                    <div ref={sentinelRef} className="h-1" aria-hidden="true" />
                  )}
                  {activeFilter === "chats" &&
                    (isLoadingMore || isSearching) && (
                      <div className="flex justify-center items-center py-3">
                        <div className="h-5 w-5 animate-spin rounded-full border-2 border-solid border-text-04 border-t-text-02" />
                      </div>
                    )}
                </>
              )}

            {/* Projects section - show if filter is 'all' or 'projects' */}
            {(activeFilter === "all" || activeFilter === "projects") &&
              displayedProjects.length > 0 && (
                <>
                  {(activeFilter === "all" || activeFilter === "projects") && (
                    <CommandMenu.Filter
                      value="projects"
                      onSelect={() => setActiveFilter("projects")}
                      isApplied={activeFilter === "projects"}
                    >
                      Projects
                    </CommandMenu.Filter>
                  )}
                  {displayedProjects.map((project) => (
                    <CommandMenu.Item
                      key={project.id}
                      value={`project-${project.id}`}
                      icon={SvgFolder}
                      rightContent={({ isHighlighted }) =>
                        isHighlighted ? (
                          <Text figureKeystroke text02>
                            ↵
                          </Text>
                        ) : (
                          <Text secondaryBody text03>
                            {formatDisplayTime(project.time)}
                          </Text>
                        )
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

          <DynamicFooter />
        </CommandMenu.Content>
      </CommandMenu>

      {/* Project creation modal */}
      <createProjectModal.Provider>
        <CreateProjectModal />
      </createProjectModal.Provider>
    </>
  );
}
