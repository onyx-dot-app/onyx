"use client";

import React, { useState, memo, useMemo, useEffect } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { useDraggable } from "@dnd-kit/core";
import useChatSessions from "@/hooks/useChatSessions";
import { deleteChatSession, renameChatSession } from "@/app/app/services/lib";
import { ChatSession } from "@/app/app/types";
import { ConfirmationModalLayout, Section } from "@opal/layouts";
import { noProp } from "@/lib/utils";
import { cn } from "@opal/utils";
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
import { Button, SidebarTab, Text, useCreateModal } from "@opal/components";
import { Hoverable } from "@opal/core";
import { DRAG_TYPES, LOCAL_STORAGE_KEYS } from "@/lib/sidebar/constants";
import {
  shouldShowMoveModal,
  showErrorNotification,
} from "@/lib/sidebar/utils";
import { handleMoveOperation } from "@/lib/sidebar/svc";
import { compactElapsed, useNowMinute } from "@/lib/sidebar/relativeTime";
import ButtonRenaming from "@/refresh-components/buttons/ButtonRenaming";
import { useAppPosition } from "@/lib/navigation/hooks";
import {
  SvgAlertCircle,
  SvgAlertTriangle,
  SvgCheck,
  SvgChevronLeft,
  SvgHelpCircle,
  SvgEdit,
  SvgFolder,
  SvgFolderIn,
  SvgFolderPlus,
  SvgMail,
  SvgMoreHorizontal,
  SvgRefreshCw,
  SvgShare,
  SvgTrash,
} from "@opal/icons";
import useOnMount from "@/hooks/useOnMount";
import { usePinChatAgent } from "@/lib/agents/hooks";
import { useChatExportMenu, useChatRunStatus } from "@/lib/chat/hooks";
import { useUnseenRuns, type ChatRunStatus } from "@/lib/chat/runStatus";
import type { IconFunctionComponent } from "@opal/types";
import UnseenMarker from "@/refresh-components/UnseenMarker";

const TOOLTIP_DELAY_MS = 150;

const RUN_STATUS_ICONS = {
  approval: { icon: SvgAlertTriangle, className: "stroke-status-warning-05" },
  question: { icon: SvgHelpCircle, className: "stroke-status-warning-05" },
  failed: { icon: SvgAlertCircle, className: "stroke-status-error-05" },
} satisfies Record<
  Exclude<ChatRunStatus, "working" | "done">,
  { icon: IconFunctionComponent; className: string }
>;

/** The mark at the row's end for a status the user should see; none while
 * working, as the title shimmers then. */
function renderRunStatusMarker(
  status: ChatRunStatus,
  label: string
): React.ReactNode {
  if (status === "working") return null;
  if (status === "done")
    return <UnseenMarker label={label} className="mx-2 block" />;
  const { icon: Icon, className } = RUN_STATUS_ICONS[status];
  return (
    <Icon
      size={16}
      role="img"
      aria-label={label}
      className={cn("mx-1 shrink-0", className)}
    />
  );
}

export interface ChatButtonProps {
  chatSession: ChatSession;
  project?: Project;
  draggable?: boolean;
  jumpShortcut?: { label: string; width: string };
}

const ChatButton = memo(
  ({
    chatSession,
    project,
    draggable = false,
    jumpShortcut,
  }: ChatButtonProps) => {
    const t = useTranslations("sidebar");
    const format = useFormatter();
    const nowMinute = useNowMinute();
    const appPosition = useAppPosition();
    const active = useMemo(
      () => appPosition.isChat() && appPosition.chat() === chatSession.id,
      [appPosition, chatSession.id]
    );
    const mounted = useOnMount();
    const runStatus = useChatRunStatus(chatSession.id);
    const [displayName, setDisplayName] = useState(
      chatSession.name || UNNAMED_CHAT
    );
    const [renaming, setRenaming] = useState(false);
    const [regeneratingTitle, setRegeneratingTitle] = useState(false);
    const [contextPoint, setContextPoint] = useState<{
      x: number;
      y: number;
    } | null>(null);
    const deleteModal = useCreateModal();
    const shareModal = useCreateModal();
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
    const { exportMenuItem } = useChatExportMenu(chatSession);
    const markUnseen = useUnseenRuns((state) => state.markUnseen);
    const markSeen = useUnseenRuns((state) => state.markSeen);
    const [menuOpen, setMenuOpen] = useState(false);
    const [optionsFocused, setOptionsFocused] = useState(false);
    const [pendingMoveProjectId, setPendingMoveProjectId] = useState<
      number | null
    >(null);
    const moveCustomAgentModal = useCreateModal();
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
      // Trimmed, as the list's own filter trims it.
      const term = searchTerm.trim().toLowerCase();
      if (!term) return projects;
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
    const unread = runStatus === "done" || runStatus === "failed";
    const canToggleUnread = runStatus === null || unread;
    const menuItems: DropdownMenuItem[] = [
      {
        kind: "action",
        id: "share",
        icon: SvgShare,
        title: t("chatButton.share.label"),
        onSelect: () => shareModal.toggle(true),
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
        id: "regenerate-title",
        icon: SvgRefreshCw,
        title: t("chatButton.regenerateTitle.label"),
        disabled: regeneratingTitle,
        onSelect: () => void handleRegenerateTitle(),
      },
      ...(canToggleUnread
        ? [
            {
              kind: "action" as const,
              id: "toggle-unread",
              icon: unread ? SvgCheck : SvgMail,
              title: unread
                ? t("chatButton.markRead.label")
                : t("chatButton.markUnread.label"),
              onSelect: () =>
                unread
                  ? markSeen(chatSession.id)
                  : markUnseen(chatSession.id, "done"),
            },
          ]
        : []),
      {
        kind: "action",
        id: "move",
        icon: SvgFolderIn,
        title: t("chatButton.moveToProject.label"),
        onSelect: (views) => views.push("move"),
      },
      exportMenuItem,
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
            onSelect: () => deleteModal.toggle(true),
          },
        ],
      },
    ];

    // Pin the chat's agent when clicking on the conversation
    const chatLink = appPosition.linkToChat(chatSession.id);

    async function handleClick(event: React.MouseEvent<HTMLElement>) {
      chatLink.onClick(event);
      await pinChatAgent(chatSession);
    }

    async function handleRename(newName: string) {
      setDisplayName(newName);
      await renameChatSession(chatSession.id, newName);
      await refreshChatSessions();
    }

    async function handleRegenerateTitle() {
      setRegeneratingTitle(true);
      try {
        const response = await renameChatSession(chatSession.id, null);
        if (!response.ok) throw new Error(`Rename failed: ${response.status}`);
        await refreshChatSessions();
      } catch (error) {
        console.error("Failed to regenerate chat title:", error);
        showErrorNotification(t("chatButton.regenerateTitleError.message"));
      } finally {
        setRegeneratingTitle(false);
      }
    }

    function handleContextMenu(event: React.MouseEvent<HTMLElement>) {
      if (renaming || event.target instanceof HTMLInputElement) return;
      event.preventDefault();
      setContextPoint({ x: event.clientX, y: event.clientY });
      setMenuOpen(true);
    }

    function handleDoubleClick(event: React.MouseEvent<HTMLElement>) {
      if (
        renaming ||
        event.metaKey ||
        event.ctrlKey ||
        event.shiftKey ||
        event.altKey ||
        (event.target instanceof Element &&
          event.target.closest('[data-testid="ChatButton/options"]'))
      )
        return;
      event.preventDefault();
      setRenaming(true);
    }

    async function handleChatDelete() {
      try {
        await deleteChatSession(chatSession.id);
        removeSession(chatSession.id);

        // Never leave the user on the chat they deleted.
        if (active) {
          if (project) {
            appPosition.openProject(project.id, { replace: true });
          } else {
            appPosition.openNewSession({ replace: true });
          }
        }

        if (project) {
          await fetchProjects();
          await refreshCurrentProjectDetails();
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
        moveCustomAgentModal.toggle(true);
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
          moveCustomAgentModal.toggle(true);
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

    const runStatusLabel = runStatus
      ? t(`chatButton.runStatus.${runStatus}.label`)
      : undefined;
    const runStatusMarker =
      runStatus && runStatusLabel
        ? renderRunStatusMarker(runStatus, runStatusLabel)
        : null;
    const elapsed = compactElapsed(chatSession.time_updated, nowMinute);
    const updatedDate = new Date(chatSession.time_updated);
    const hasUpdatedDate = !Number.isNaN(updatedDate.getTime());
    const timeLabel = hasUpdatedDate ? (
      <span className="mx-1 shrink-0">
        <Text
          font="secondary-body"
          color="text-03"
          wordWrap="whitespace-nowrap"
        >
          {elapsed
            ? format.number(elapsed.value, {
                style: "unit",
                unit: elapsed.unit,
                unitDisplay: "narrow",
              })
            : t("chatButton.updatedNow.label")}
        </Text>
      </span>
    ) : null;
    const restingMarker = runStatusMarker ?? timeLabel;
    const tooltip =
      renaming || menuOpen ? undefined : (
        <Section gap={0.25} alignItems="start" width="fit" height="fit">
          <Text font="secondary-action" color="inherit">
            {displayName}
          </Text>
          {runStatusLabel && (
            <Text font="secondary-body" color="inherit">
              {runStatusLabel}
            </Text>
          )}
          {hasUpdatedDate && (
            <Text font="secondary-body" color="inherit">
              {t("chatButton.updatedAt", {
                date: format.dateTime(updatedDate, {
                  dateStyle: "medium",
                  timeStyle: "short",
                }),
              })}
            </Text>
          )}
        </Section>
      );
    const optionsButton = (
      <Dropdown.Trigger asChild>
        <Button
          icon={SvgMoreHorizontal}
          prominence="internal"
          size="sm"
          interaction={menuOpen ? "hover" : "rest"}
          aria-label={t("chatButton.options.label")}
          onFocus={() => setOptionsFocused(true)}
          onBlur={() => setOptionsFocused(false)}
        />
      </Dropdown.Trigger>
    );

    const rightMenu = (
      <>
        {/* The click stays here: the row underneath opens the chat. */}
        <div
          role="presentation"
          data-testid="ChatButton/options"
          onClick={noProp()}
        >
          {/* While renaming the row is an input, so the menu stays away unless
              its own list is already open. */}
          {!renaming && runStatusMarker && (
            <span
              data-touch-run-marker
              className="pointer-events-none hidden no-hover:block absolute end-6 top-1/2 -translate-y-1/2"
            >
              {runStatusMarker}
            </span>
          )}
          {(!renaming || menuOpen) &&
            (restingMarker ? (
              <Hoverable.Item
                group="ChatButton"
                variant="replace-on-hover"
                resting={restingMarker}
              >
                {optionsButton}
              </Hoverable.Item>
            ) : (
              <Hoverable.Item group="ChatButton">
                {optionsButton}
              </Hoverable.Item>
            ))}
        </div>
        <Dropdown.Data
          label={t("chatButton.options.label")}
          items={menuItems}
          views={{ move: moveView }}
        />
      </>
    );

    const jumpHint =
      jumpShortcut && !renaming && !menuOpen && !optionsFocused ? (
        <span dir="ltr" aria-hidden="true" className="pointer-events-none!">
          <Text
            font="figure-keystroke"
            color="text-03"
            wordWrap="whitespace-nowrap"
          >
            {jumpShortcut.label}
          </Text>
        </span>
      ) : null;

    const popover = (
      <Dropdown
        width={60}
        side="right"
        open={menuOpen}
        virtualAnchor={
          contextPoint
            ? {
                getBoundingClientRect: () =>
                  new DOMRect(contextPoint.x, contextPoint.y, 0, 0),
              }
            : undefined
        }
        onOpenChange={(open) => {
          setMenuOpen(open);
          if (!open) setContextPoint(null);
        }}
      >
        <Hoverable.Root
          group="ChatButton"
          data-testid="ChatButton"
          onContextMenu={handleContextMenu}
          onDoubleClick={handleDoubleClick}
          interaction={menuOpen ? "hover" : "rest"}
        >
          <SidebarTab
            /* While renaming, drop the click target so the input stays usable. */
            href={isDragging || renaming ? undefined : chatLink.href}
            onClick={renaming ? undefined : handleClick}
            selected={active}
            loading={runStatus === "working" || regeneratingTitle}
            tooltip={tooltip}
            tooltipDelay={TOOLTIP_DELAY_MS}
            rightChildren={jumpHint ?? rightMenu}
            rightChildrenAtRest={
              (jumpHint && jumpShortcut?.width) ||
              (!renaming &&
                (runStatusMarker ? true : timeLabel ? "2rem" : false))
            }
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
        <deleteModal.Provider>
          <ConfirmationModalLayout
            title={t("chatButton.deleteConfirmation.title")}
            icon={SvgTrash}
            onClose={() => deleteModal.toggle(false)}
            submit={
              <Button
                variant="danger"
                onClick={() => {
                  deleteModal.toggle(false);
                  handleChatDelete();
                }}
              >
                {t("chatButton.deleteConfirmation.confirmButton.label")}
              </Button>
            }
          >
            {t("chatButton.deleteConfirmation.description")}
          </ConfirmationModalLayout>
        </deleteModal.Provider>

        <moveCustomAgentModal.Provider>
          <MoveCustomAgentChatModal
            onCancel={() => {
              moveCustomAgentModal.toggle(false);
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
              moveCustomAgentModal.toggle(false);
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
        </moveCustomAgentModal.Provider>

        <shareModal.Provider>
          <ShareChatSessionModal
            chatSession={chatSession}
            onClose={() => shareModal.toggle(false)}
          />
        </shareModal.Provider>

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
