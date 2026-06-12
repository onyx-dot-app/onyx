"use client";

import React, { useCallback, useMemo, useState } from "react";
import { deleteChatSession } from "@/app/app/services/lib";
import {
  moveChatSession as moveChatSessionService,
  removeChatSessionFromProject as removeChatSessionFromProjectService,
} from "@/app/app/projects/projectsService";
import { useProjectsContext } from "@/providers/ProjectsContext";
import { ChatSession } from "@/app/app/interfaces";
import AgentAvatar from "@/refresh-components/avatars/AgentAvatar";
import { useAgents } from "@/lib/agents/hooks";
import useChatSessions from "@/hooks/useChatSessions";
import {
  Button,
  Card,
  LineItemButton,
  Popover,
  PopoverMenu,
  Text,
} from "@opal/components";
import { Hoverable } from "@opal/core";
import { DEFAULT_AGENT_ID, UNNAMED_CHAT } from "@/lib/constants";
import {
  SvgBubbleText,
  SvgFolder,
  SvgFolderIn,
  SvgMoreHorizontal,
  SvgSimpleLoader,
  SvgTrash,
} from "@opal/icons";
import { timeAgo } from "@opal/time";
import type { IconFunctionComponent } from "@opal/types";
import { noProp } from "@/lib/utils";
import MoveCustomAgentChatModal from "@/sections/modals/MoveCustomAgentChatModal";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import LineItem from "@/refresh-components/buttons/LineItem";
import { PopoverSearchInput } from "@/sections/sidebar/ChatButton";

const LS_HIDE_MOVE_CUSTOM_AGENT_MODAL_KEY = "onyx:hideMoveCustomAgentModal";

interface ProjectChatItemProps {
  chat: ChatSession;
  projectId: number;
  icon: IconFunctionComponent;
  afterRefresh: () => void;
}

function ProjectChatItem({
  chat,
  projectId,
  icon,
  afterRefresh,
}: ProjectChatItemProps) {
  const [popoverOpen, setPopoverOpen] = useState(false);
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const [pendingMoveProjectId, setPendingMoveProjectId] = useState<
    number | null
  >(null);
  const [showMoveCustomAgentModal, setShowMoveCustomAgentModal] =
    useState(false);
  const [showMoveOptions, setShowMoveOptions] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");

  const { refreshChatSessions, removeSession } = useChatSessions();
  const { fetchProjects, projects } = useProjectsContext();

  const isChatUsingDefaultAgent = chat.persona_id === DEFAULT_AGENT_ID;

  const filteredProjects = projects.filter((project) =>
    project.name.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const handleConfirmDelete = useCallback(
    async (e: React.MouseEvent<HTMLButtonElement>) => {
      e.stopPropagation();
      await deleteChatSession(chat.id);
      removeSession(chat.id);
      await refreshChatSessions();
      await fetchProjects();
      setIsDeleteModalOpen(false);
      setPopoverOpen(false);
      afterRefresh();
    },
    [chat, refreshChatSessions, removeSession, fetchProjects, afterRefresh]
  );

  const performMove = useCallback(
    async (targetProjectId: number) => {
      await moveChatSessionService(targetProjectId, chat.id);
      await fetchProjects();
      await refreshChatSessions();
      setPopoverOpen(false);
      afterRefresh();
    },
    [chat.id, fetchProjects, refreshChatSessions, afterRefresh]
  );

  const handleMoveChatSession = useCallback(
    async (item: { id: number; label: string }) => {
      const hideModal =
        typeof window !== "undefined" &&
        window.localStorage.getItem(LS_HIDE_MOVE_CUSTOM_AGENT_MODAL_KEY) ===
          "true";

      if (!isChatUsingDefaultAgent && !hideModal) {
        setPendingMoveProjectId(item.id);
        setShowMoveCustomAgentModal(true);
        return;
      }

      await performMove(item.id);
    },
    [isChatUsingDefaultAgent, performMove]
  );

  const handleRemoveFromProject = useCallback(async () => {
    await removeChatSessionFromProjectService(chat.id);
    await fetchProjects();
    await refreshChatSessions();
    afterRefresh();
    setPopoverOpen(false);
  }, [chat.id, fetchProjects, refreshChatSessions, afterRefresh]);

  const popoverItems = useMemo(() => {
    if (!showMoveOptions) {
      return [
        <LineItem
          key="move"
          icon={SvgFolderIn}
          onClick={noProp(() => setShowMoveOptions(true))}
        >
          Move to Project
        </LineItem>,
        <LineItem
          key="remove"
          icon={SvgFolder}
          onClick={noProp(handleRemoveFromProject)}
        >
          {`Remove from ${projects.find((p) => p.id === projectId)?.name ?? "Project"}`}
        </LineItem>,
        null,
        <LineItem
          key="delete"
          icon={SvgTrash}
          onClick={noProp(() => setIsDeleteModalOpen(true))}
          danger
        >
          Delete
        </LineItem>,
      ];
    }
    return [
      <PopoverSearchInput
        key="search"
        setShowMoveOptions={setShowMoveOptions}
        onSearch={setSearchTerm}
      />,
      ...filteredProjects
        .filter((candidate) => candidate.id !== projectId)
        .map((target) => (
          <LineItem
            key={target.id}
            icon={SvgFolder}
            onClick={noProp(() =>
              handleMoveChatSession({ id: target.id, label: target.name })
            )}
          >
            {target.name}
          </LineItem>
        )),
    ];
  }, [
    showMoveOptions,
    projects,
    projectId,
    filteredProjects,
    handleMoveChatSession,
    handleRemoveFromProject,
  ]);

  return (
    <>
      <Hoverable.Root group={chat.id} width="full">
        <LineItemButton
          href={`/app?chatId=${chat.id}`}
          group={chat.id}
          icon={icon}
          title={chat.name || UNNAMED_CHAT}
          description={`Last message ${timeAgo(chat.time_updated) ?? ""}`}
          sizePreset="main-ui"
          interaction={popoverOpen ? "active" : undefined}
          rightChildren={
            <Hoverable.Item group={chat.id} variant="appear-on-hover">
              <div className="-my-1">
                <Popover open={popoverOpen} onOpenChange={setPopoverOpen}>
                  <Popover.Trigger
                    asChild
                    onClick={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      setPopoverOpen(!popoverOpen);
                    }}
                  >
                    <div className="p-1 rounded-sm cursor-pointer select-none">
                      <SvgMoreHorizontal size={20} />
                    </div>
                  </Popover.Trigger>
                  <Popover.Content
                    align="end"
                    side="right"
                    avoidCollisions
                    sideOffset={8}
                  >
                    <PopoverMenu>{popoverItems}</PopoverMenu>
                  </Popover.Content>
                </Popover>
              </div>
            </Hoverable.Item>
          }
        />
      </Hoverable.Root>

      {isDeleteModalOpen && (
        <ConfirmationModalLayout
          title="Delete Chat"
          icon={SvgTrash}
          onClose={() => setIsDeleteModalOpen(false)}
          submit={
            <Button variant="danger" onClick={handleConfirmDelete}>
              Delete
            </Button>
          }
        >
          Are you sure you want to delete this chat? This action cannot be
          undone.
        </ConfirmationModalLayout>
      )}

      {showMoveCustomAgentModal && (
        <MoveCustomAgentChatModal
          onCancel={() => {
            setShowMoveCustomAgentModal(false);
            setPendingMoveProjectId(null);
          }}
          onConfirm={async (doNotShowAgain) => {
            if (doNotShowAgain && typeof window !== "undefined") {
              window.localStorage.setItem(
                LS_HIDE_MOVE_CUSTOM_AGENT_MODAL_KEY,
                "true"
              );
            }
            const target = pendingMoveProjectId;
            setShowMoveCustomAgentModal(false);
            setPendingMoveProjectId(null);
            if (target != null) await performMove(target);
          }}
        />
      )}
    </>
  );
}

export default function ProjectChatSessionList() {
  const {
    currentProjectDetails,
    currentProjectId,
    refreshCurrentProjectDetails,
    isLoadingProjectDetails,
  } = useProjectsContext();
  const { agents } = useAgents();

  const projectChats: ChatSession[] = useMemo(() => {
    const sessions = currentProjectDetails?.project?.chat_sessions || [];
    return [...sessions].sort(
      (a, b) =>
        new Date(b.time_updated).getTime() - new Date(a.time_updated).getTime()
    );
  }, [currentProjectDetails?.project?.chat_sessions]);

  if (!currentProjectId) return null;

  return (
    <div className="flex flex-col gap-6 mx-auto">
      <div />

      <div>
        <div className="px-3 py-2">
          <Text as="p" font="secondary-body" color="text-02">
            Recent Chats
          </Text>
        </div>

        {isLoadingProjectDetails && !currentProjectDetails ? (
          <SvgSimpleLoader className="mx-4" />
        ) : projectChats.length === 0 ? (
          <Card rounding="md" border="dashed" background="none" padding="sm">
            <div className="p-1">
              <Text as="p" font="secondary-body" color="text-02">
                No chats yet.
              </Text>
            </div>
          </Card>
        ) : (
          projectChats.map((chat) => {
            const personaIdToFeatured =
              currentProjectDetails?.persona_id_to_is_featured || {};
            const isFeatured = personaIdToFeatured[chat.persona_id];
            const agent =
              isFeatured === false
                ? agents.find((a) => a.id === chat.persona_id)
                : undefined;
            const icon: IconFunctionComponent = agent
              ? ((() => (
                  <AgentAvatar agent={agent} size={18} />
                )) as IconFunctionComponent)
              : SvgBubbleText;

            return (
              <div key={chat.id} className="px-1">
                <ProjectChatItem
                  chat={chat}
                  projectId={currentProjectId}
                  icon={icon}
                  afterRefresh={refreshCurrentProjectDetails}
                />
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
