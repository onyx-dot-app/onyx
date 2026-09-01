"use client";

import React, { useState, useMemo, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import type { Route } from "next";
import { useAppPosition } from "@/lib/position/hooks";
import CommandMenu, {
  useCommandMenuContext,
} from "@/refresh-components/commandmenu/CommandMenu";
import { useProjects } from "@/lib/projects/hooks";
import { useCreateModal } from "@opal/components";
import { CreateProjectModal } from "@/lib/projects/components";
import { timeAgo } from "@opal/time";
import { highlightMatch } from "@/lib/sidebar/utils";
import Text from "@/refresh-components/texts/Text";
import useChatSearchOptimistic from "@/lib/sidebar/hooks";
import {
  SvgEditBig,
  SvgFolder,
  SvgFolderPlus,
  SvgBubbleText,
  SvgArrowUpDown,
  SvgKeystroke,
} from "@opal/icons";
import TextSeparator from "@/refresh-components/TextSeparator";

/**
 * Dynamic footer that shows contextual action labels based on highlighted item type
 */
function DynamicFooter() {
  const t = useTranslations("sidebar");
  const { highlightedItemType } = useCommandMenuContext();

  // "Show all" for filters, "Open" for everything else (items, actions, or no highlight)
  const actionLabel =
    highlightedItemType === "filter"
      ? t("chatSearch.footer.showAllAction.label")
      : t("chatSearch.footer.openAction.label");

  return (
    <CommandMenu.Footer
      leftActions={
        <>
          <CommandMenu.FooterAction
            icon={SvgArrowUpDown}
            label={t("chatSearch.footer.selectAction.label")}
          />
          <CommandMenu.FooterAction icon={SvgKeystroke} label={actionLabel} />
        </>
      }
    />
  );
}

interface ChatSearchCommandMenuProps {
  /** Renders the control that opens the menu. */
  trigger: (open: () => void) => React.ReactNode;
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
  const t = useTranslations("sidebar");
  const [open, setOpen] = useState(false);
  const [searchValue, setSearchValue] = useState("");
  const [activeFilter, setActiveFilter] = useState<
    "all" | "chats" | "projects"
  >("all");
  const [initialProjectName, setInitialProjectName] = useState<
    string | undefined
  >();
  const appPosition = useAppPosition();
  const router = useRouter();

  // Data hooks
  const { projects } = useProjects();
  const createProjectModal = useCreateModal();

  // Constants for preview limits
  const PREVIEW_CHATS_LIMIT = 4;
  const PREVIEW_PROJECTS_LIMIT = 3;

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
      return [{ id: "chats", label: t("chatSearch.sessionsFilter.label") }];
    }
    if (activeFilter === "projects") {
      return [{ id: "projects", label: t("chatSearch.projectsFilter.label") }];
    }
    return [];
  }, [activeFilter, t]);

  const handleFilterRemove = useCallback(() => {
    setActiveFilter("all");
  }, []);

  // Navigation handlers
  const handleNewSession = useCallback(() => {
    router.push("/app");
    setOpen(false);
  }, [router]);

  const handleChatSelect = useCallback(
    (chatId: string) => {
      appPosition.openChat(chatId);
      setOpen(false);
    },
    [appPosition]
  );

  const handleProjectSelect = useCallback(
    (projectId: number) => {
      appPosition.openProject(projectId);
      setOpen(false);
    },
    [appPosition]
  );

  const handleNewProject = useCallback(
    (initialName?: string) => {
      setInitialProjectName(initialName);
      setOpen(false);
      createProjectModal.toggle(true);
    },
    [createProjectModal]
  );

  const handleOpen = useCallback(() => setOpen(true), []);

  const handleOpenChange = useCallback((newOpen: boolean) => {
    setOpen(newOpen);
    if (!newOpen) {
      setSearchValue("");
      setActiveFilter("all");
    }
  }, []);

  const handleEmptyBackspace = useCallback(() => {
    if (activeFilter !== "all") {
      // Remove active filter, return to root menu
      setActiveFilter("all");
    } else {
      // No filter active, close the menu
      setOpen(false);
    }
  }, [activeFilter]);

  const hasSearchValue = searchValue.trim().length > 0;

  return (
    <>
      {trigger(handleOpen)}

      <CommandMenu open={open} onOpenChange={handleOpenChange}>
        <CommandMenu.Content>
          <CommandMenu.Header
            placeholder={t("chatSearch.searchInput.placeholder")}
            value={searchValue}
            onValueChange={setSearchValue}
            filters={headerFilters}
            onFilterRemove={handleFilterRemove}
            onClose={() => setOpen(false)}
            onEmptyBackspace={handleEmptyBackspace}
          />

          <CommandMenu.List
            emptyMessage={
              hasSearchValue
                ? t("chatSearch.list.noResults.text")
                : t("chatSearch.list.empty.text")
            }
          >
            {/* New Session action - always visible in "all" filter, even during search */}
            {activeFilter === "all" && (
              <CommandMenu.Action
                value="new-session"
                icon={SvgEditBig}
                onSelect={handleNewSession}
                defaultHighlight={!hasSearchValue}
              >
                {t("chatSearch.newSession.label")}
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
                      isApplied={
                        activeFilter === "chats" ||
                        filteredChats.length <= PREVIEW_CHATS_LIMIT
                      }
                    >
                      {activeFilter === "chats"
                        ? t("chatSearch.recentFilter.label")
                        : t("chatSearch.recentSessionsFilter.label")}
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
                          <Text
                            secondaryBody
                            text03
                            data-testid="command-menu-timestamp"
                          >
                            {timeAgo(chat.time)}
                          </Text>
                        )
                      }
                      onSelect={() => handleChatSelect(chat.id)}
                    >
                      {highlightMatch(chat.label, searchValue)}
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
            {(activeFilter === "all" || activeFilter === "projects") && (
              <>
                <CommandMenu.Filter
                  value="projects"
                  onSelect={() => setActiveFilter("projects")}
                  isApplied={
                    activeFilter === "projects" ||
                    filteredProjects.length <= PREVIEW_PROJECTS_LIMIT
                  }
                >
                  {t("chatSearch.projectsFilter.label")}
                </CommandMenu.Filter>
                {/* New Project action - shown after Projects filter when no search term */}
                {!hasSearchValue && activeFilter === "all" && (
                  <CommandMenu.Action
                    value="new-project"
                    icon={SvgFolderPlus}
                    onSelect={() => handleNewProject()}
                  >
                    {t("chatSearch.newProject.label")}
                  </CommandMenu.Action>
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
                        <Text
                          secondaryBody
                          text03
                          data-testid="command-menu-timestamp"
                        >
                          {timeAgo(project.time)}
                        </Text>
                      )
                    }
                    onSelect={() => handleProjectSelect(project.id)}
                  >
                    {highlightMatch(project.label, searchValue)}
                  </CommandMenu.Item>
                ))}
              </>
            )}

            {/* Create New Project with search term - shown at bottom when searching */}
            {hasSearchValue &&
              (activeFilter === "all" || activeFilter === "projects") && (
                <CommandMenu.Action
                  value="create-project-with-name"
                  icon={SvgFolderPlus}
                  onSelect={() => handleNewProject(searchValue.trim())}
                >
                  {t.rich("chatSearch.createNamedProject.label", {
                    projectName: searchValue.trim(),
                    name: (chunks) => (
                      <span className="text-text-05">{chunks}</span>
                    ),
                  })}
                </CommandMenu.Action>
              )}

            {/* No more results divider - shown when no results for the active filter */}
            {((activeFilter === "chats" && displayedChats.length === 0) ||
              (activeFilter === "projects" && displayedProjects.length === 0) ||
              (activeFilter === "all" &&
                displayedChats.length === 0 &&
                displayedProjects.length === 0)) && (
              <TextSeparator
                text={t("chatSearch.noMoreResults.text")}
                className="mt-auto mb-2"
              />
            )}
          </CommandMenu.List>

          <DynamicFooter />
        </CommandMenu.Content>
      </CommandMenu>

      {/* Project creation modal */}
      <createProjectModal.Provider>
        <CreateProjectModal initialProjectName={initialProjectName} />
      </createProjectModal.Provider>
    </>
  );
}
