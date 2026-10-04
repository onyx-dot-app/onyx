"use client";

import React, { useState, memo, useMemo, useEffect } from "react";
import { useTranslations } from "next-intl";
import { useDraggable } from "@dnd-kit/core";
import useChatSessions from "@/hooks/useChatSessions";
import { deleteChatSession, renameChatSession } from "@/app/app/services/lib";
import { ChatSession } from "@/app/app/interfaces";
import { ConfirmationModalLayout } from "@opal/layouts";
import { noProp } from "@/lib/utils";
import {
  Dropdown,
  type DropdownMenuItem,
  type DropdownView,
} from "@opal/components";
import type { Project } from "@/lib/projects/types";
import {
  removeChatSessionFromProject,
  createProject as createProjectService,
} from "@/lib/projects/svc";
import { useProjectsContext } from "@/lib/projects/providers";
import { MoveCustomAgentChatModal } from "@/lib/agents/components";
import { UNNAMED_CHAT } from "@/lib/constants";
import ShareChatSessionModal from "@/sections/modals/ShareChatSessionModal";
import { Button, SidebarTab } from "@opal/components";
import { Hoverable } from "@opal/core";
import { DRAG_TYPES, LOCAL_STORAGE_KEYS } from "@/lib/sidebar/constants";
import {
  shouldShowMoveModal,
  showErrorNotification,
} from "@/lib/sidebar/utils";
import { handleMoveOperation } from "@/lib/sidebar/svc";
import ButtonRenaming from "@/refresh-components/buttons/ButtonRenaming";
import { useAppPosition } from "@/lib/position/hooks";
import {
  SvgChevronLeft,
  SvgEdit,
  SvgFolder,
  SvgFolderIn,
  SvgFolderPlus,
  SvgMoreHorizontal,
  SvgShare,
  SvgTrash,
} from "@opal/icons";
import useOnMount from "@/hooks/useOnMount";
import { usePinChatAgent } from "@/lib/agents/hooks";

export interface ChatButtonProps {
  chatSession: ChatSession;
  project?: Project;
  draggable?: boolean;
}

const ChatButton = memo(
  ({ chatSession, project, draggable = false }: ChatButtonProps) => {
    const t = useTranslations("sidebar");
    const appPosition = useAppPosition();
    const activeSidebarTab = useAppPosition();
    const active = useMemo(
      () =>
        activeSidebarTab.isChat() && activeSidebarTab.chat() === chatSession.id,
      [activeSidebarTab, chatSession.id]
    );
    const mounted = useOnMount();
    const [displayName, setDisplayName] = useState(
      chatSession.name || UNNAMED_CHAT
    );
    const [renaming, setRenaming] = useState(false);
    const [deleteConfirmationModalOpen, setDeleteConfirmationModalOpen] =
      useState(false);
    const [showShareModal, setShowShareModal] = useState(false);
    const [searchTerm, setSearchTerm] = useState("");
    const { refreshChatSessions, removeSession } = useChatSessions();
    const {
      refreshCurrentProjectDetails,
      projects,
      fetchProjects,
      currentProjectId,
      createProject,
    } = useProjectsContext();
    const pinChatAgent = usePinChatAgent();
    const [menuOpen, setMenuOpen] = useState(false);
    const [pendingMoveProjectId, setPendingMoveProjectId] = useState<
      number | null
    >(null);
    const [showMoveCustomAgentModal, setShowMoveCustomAgentModal] =
      useState(false);
    const [navigateAfterMoveProjectId, setNavigateAfterMoveProjectId] =
      useState<number | null>(null);

    // Drag and drop setup for chat sessions
    const dragId = `${DRAG_TYPES.CHAT}-${chatSession.id}`;
    // `attributes` is intentionally dropped: it turns the wrapper into a
    // focusable role="button", which adds a second tab stop per row and lets
    // Enter/Space start a keyboard drag that looks like the chat is disabled.
    const { listeners, setNodeRef, transform, isDragging } = useDraggable({
      id: dragId,
      data: {
        type: DRAG_TYPES.CHAT,
        chatSession,
        projectId: project?.id,
      },
      disabled: !draggable || renaming,
    });

    // Sync local name state when chatSession.name changes (e.g., after auto-naming)
    useEffect(() => {
      const newName = chatSession.name || UNNAMED_CHAT;
      const oldName = displayName;

      // Only animate if transitioning from UNNAMED_CHAT to a real name
      if (oldName === UNNAMED_CHAT && newName !== UNNAMED_CHAT && mounted) {
        // Type out the name character by character
        let currentIndex = 0;
        const typingInterval = setInterval(() => {
          currentIndex++;
          setDisplayName(newName.slice(0, currentIndex));

          if (currentIndex >= newName.length) {
            clearInterval(typingInterval);
          }
        }, 30); // 30ms per character

        return () => clearInterval(typingInterval);
      } else {
        // No animation for other changes (manual rename, initial load, etc.)
        setDisplayName(newName);
      }
    }, [chatSession.name, mounted]);

    const filteredProjects = useMemo(() => {
      if (!searchTerm) return projects;
      const term = searchTerm.toLowerCase();
      return projects.filter((project) =>
        project.name.toLowerCase().includes(term)
      );
    }, [projects, searchTerm]);

    const availableProjects = filteredProjects.filter(
      (candidateProject) => candidateProject.id !== project?.id
    );
    // The move page: the view's own search filters the projects; the way
    // back and the create row stay pinned above the filter.
    const moveView: DropdownView = {
      search: {
        placeholder: t("chatButton.projectSearchInput.placeholder"),
        onChange: setSearchTerm,
      },
      items: [
        {
          kind: "action",
          id: "back",
          pinned: true,
          icon: SvgChevronLeft,
          title: t("chatButton.moveToProject.label"),
          onSelect: (views) => views.pop(),
        },
        ...projects
          .filter((candidateProject) => candidateProject.id !== project?.id)
          .map(
            (targetProject): DropdownMenuItem => ({
              kind: "action",
              id: `project-${targetProject.id}`,
              icon: SvgFolder,
              title: targetProject.name,
              onSelect: () => handleChatMove(targetProject),
            })
          ),
        // A create row when no project matches the search.
        ...(availableProjects.length === 0 && searchTerm.trim() !== ""
          ? [
              {
                kind: "group" as const,
                items: [
                  {
                    kind: "action" as const,
                    id: "create-new",
                    pinned: true,
                    icon: SvgFolderPlus,
                    title: t("chatButton.createProject.label", {
                      projectName: searchTerm.trim(),
                    }),
                    onSelect: () =>
                      handleCreateProjectAndMove(searchTerm.trim()),
                  },
                ],
              },
            ]
          : []),
      ],
    };
    const menuItems: DropdownMenuItem[] = [
      {
        kind: "action",
        id: "share",
        icon: SvgShare,
        title: t("chatButton.share.label"),
        onSelect: () => setShowShareModal(true),
      },
      {
        kind: "action",
        id: "rename",
        icon: SvgEdit,
        title: t("chatButton.rename.label"),
        onSelect: () => setRenaming(true),
      },
      {
        kind: "action",
        id: "move",
        icon: SvgFolderIn,
        opensView: true,
        title: t("chatButton.moveToProject.label"),
        onSelect: (views) => views.push("move"),
      },
      ...(project
        ? [
            {
              kind: "action" as const,
              id: "remove",
              icon: SvgFolder,
              title: t("chatButton.removeFromProject.label", {
                projectName: project.name,
              }),
              onSelect: () => handleRemoveFromProject(),
            },
          ]
        : []),
      {
        kind: "group",
        items: [
          {
            kind: "action",
            id: "delete",
            icon: SvgTrash,
            danger: true,
            title: t("chatButton.delete.label"),
            onSelect: () => setDeleteConfirmationModalOpen(true),
          },
        ],
      },
    ];

    // Pin the chat's agent when clicking on the conversation
    async function handleClick() {
      await pinChatAgent(chatSession);
    }

    async function handleRename(newName: string) {
      setDisplayName(newName);
      await renameChatSession(chatSession.id, newName);
      await refreshChatSessions();
    }

    async function handleChatDelete() {
      try {
        await deleteChatSession(chatSession.id);
        removeSession(chatSession.id);

        if (project) {
          await fetchProjects();
          await refreshCurrentProjectDetails();

          // Only route if the deleted chat is the currently opened chat session
          if (active) {
            appPosition.openProject(project.id);
          }
        }
        await refreshChatSessions();
      } catch (error) {
        console.error("Failed to delete chat:", error);
        showErrorNotification(t("chatButton.deleteError.message"));
      }
    }

    async function performMove(targetProjectId: number) {
      try {
        await handleMoveOperation({
          chatSession,
          targetProjectId,
          refreshChatSessions,
          refreshCurrentProjectDetails,
          fetchProjects,
          currentProjectId,
        });
        setSearchTerm("");
      } catch (error) {
        // handleMoveOperation already handles error notification
        console.error("Failed to move chat:", error);
      }
    }

    async function handleChatMove(targetProject: Project) {
      if (shouldShowMoveModal(chatSession)) {
        setPendingMoveProjectId(targetProject.id);
        setShowMoveCustomAgentModal(true);
        return;
      }
      await performMove(targetProject.id);
    }

    async function handleRemoveFromProject() {
      try {
        await removeChatSessionFromProject(chatSession.id);
        const projectRefreshPromise = currentProjectId
          ? refreshCurrentProjectDetails()
          : fetchProjects();
        await Promise.all([refreshChatSessions(), projectRefreshPromise]);
        setSearchTerm("");
      } catch (error) {
        console.error("Failed to remove chat from project:", error);
      }
    }

    async function handleCreateProjectAndMove(projectName: string) {
      try {
        // Create the new project using the service directly (without navigation)
        const newProject = await createProjectService(projectName);

        // Refresh projects list to include the new project
        await fetchProjects();

        // Mark that we want to navigate to this project after moving
        setNavigateAfterMoveProjectId(newProject.id);

        // Check if we should show the move modal for custom agents
        if (shouldShowMoveModal(chatSession)) {
          setPendingMoveProjectId(newProject.id);
          setShowMoveCustomAgentModal(true);
          setSearchTerm("");
          return;
        }

        // Move the chat to the newly created project
        await performMove(newProject.id);

        // Navigate to the new project to see the chat
        appPosition.openProject(newProject.id);
        setNavigateAfterMoveProjectId(null);
      } catch (error) {
        console.error("Failed to create project and move chat:", error);
        showErrorNotification(t("chatButton.createProjectError.message"));
        setNavigateAfterMoveProjectId(null);
      }
    }

    const rightMenu = (
      <>
        <Dropdown.Trigger asChild>
          {/* The click stays here: the row underneath opens the chat. */}
          <div
            role="presentation"
            data-testid="ChatButton/options"
            onClick={noProp()}
          >
            {/* While renaming the row is an input, so the menu stays away unless
                its own list is already open. */}
            {(!renaming || menuOpen) && (
              <Hoverable.Item group="ChatButton">
                <Button
                  icon={SvgMoreHorizontal}
                  prominence="internal"
                  size="sm"
                  interaction={menuOpen ? "hover" : "rest"}
                  aria-label={t("chatButton.options.label")}
                />
              </Hoverable.Item>
            )}
          </div>
        </Dropdown.Trigger>
        <Dropdown.Data
          label={t("chatButton.options.label")}
          items={menuItems}
          views={{ move: moveView }}
        />
      </>
    );

    const popover = (
      <Dropdown onOpenChange={setMenuOpen}>
        <Hoverable.Root
          group="ChatButton"
          data-testid="ChatButton"
          interaction={menuOpen ? "hover" : "rest"}
        >
          <SidebarTab
            /* While renaming, drop the click target so the input stays usable. */
            href={
              isDragging || renaming
                ? undefined
                : `/app?chatId=${chatSession.id}`
            }
            onClick={renaming ? undefined : handleClick}
            selected={active}
            rightChildren={rightMenu}
            nested={!!project}
          >
            {renaming ? (
              <ButtonRenaming
                initialName={chatSession.name}
                onRename={handleRename}
                onClose={() => setRenaming(false)}
              />
            ) : (
              displayName
            )}
          </SidebarTab>
        </Hoverable.Root>
      </Dropdown>
    );

    return (
      <>
        {deleteConfirmationModalOpen && (
          <ConfirmationModalLayout
            title={t("chatButton.deleteConfirmation.title")}
            icon={SvgTrash}
            onClose={() => setDeleteConfirmationModalOpen(false)}
            submit={
              <Button
                variant="danger"
                onClick={() => {
                  setDeleteConfirmationModalOpen(false);
                  handleChatDelete();
                }}
              >
                {t("chatButton.deleteConfirmation.confirmButton.label")}
              </Button>
            }
          >
            {t("chatButton.deleteConfirmation.description")}
          </ConfirmationModalLayout>
        )}

        {showMoveCustomAgentModal && (
          <MoveCustomAgentChatModal
            onCancel={() => {
              setShowMoveCustomAgentModal(false);
              setPendingMoveProjectId(null);
              setNavigateAfterMoveProjectId(null);
            }}
            onConfirm={async (doNotShowAgain: boolean) => {
              if (doNotShowAgain && typeof window !== "undefined") {
                window.localStorage.setItem(
                  LOCAL_STORAGE_KEYS.HIDE_MOVE_CUSTOM_AGENT_MODAL,
                  "true"
                );
              }
              const target = pendingMoveProjectId;
              const shouldNavigate = navigateAfterMoveProjectId;
              setShowMoveCustomAgentModal(false);
              setPendingMoveProjectId(null);
              if (target != null) {
                await performMove(target);
                // Navigate if this was triggered by creating a new project
                if (shouldNavigate != null) {
                  appPosition.openProject(shouldNavigate);
                  setNavigateAfterMoveProjectId(null);
                }
              }
            }}
          />
        )}

        {showShareModal && (
          <ShareChatSessionModal
            chatSession={chatSession}
            onClose={() => setShowShareModal(false)}
          />
        )}

        {draggable ? (
          <div
            ref={setNodeRef}
            style={{
              transform: transform
                ? `translate3d(0px, ${transform.y}px, 0)`
                : undefined,
              opacity: isDragging ? 0.5 : 1,
            }}
            {...(mounted ? listeners : {})}
          >
            {popover}
          </div>
        ) : (
          popover
        )}
      </>
    );
  }
);
ChatButton.displayName = "ChatButton";

export default ChatButton;
