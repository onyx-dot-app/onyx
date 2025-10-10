"use client";

import React, { useState, useEffect, useMemo } from "react";
import {
  Project,
  useProjectsContext,
} from "@/app/chat/projects/ProjectsContext";
import NavigationTab from "@/refresh-components/buttons/NavigationTab";
import Text from "@/refresh-components/Text";
import SvgFolder from "@/icons/folder";
import SvgEdit from "@/icons/edit";
import { PopoverMenu } from "@/components/ui/popover";
import SvgTrash from "@/icons/trash";
import ConfirmationModal from "@/refresh-components/modals/ConfirmationModal";
import Button from "@/refresh-components/buttons/Button";
import { ChatButton } from "@/sections/sidebar/AppSidebar";
import { useAppParams, useAppRouter } from "@/hooks/appNavigation";
import SvgFolderPlus from "@/icons/folder-plus";
import {
  ModalIds,
  useChatModal,
} from "@/refresh-components/contexts/ChatModalContext";
import { SEARCH_PARAM_NAMES } from "@/app/chat/services/searchParams";
import { cn, noProp } from "@/lib/utils";
import { OpenFolderIcon } from "@/components/icons/CustomIcons";

import { SvgProps } from "@/icons";
import { useDroppable } from "@dnd-kit/core";

interface ProjectFolderProps {
  project: Project;
}

function ProjectFolder({ project }: ProjectFolderProps) {
  const route = useAppRouter();
  const params = useAppParams();
  const [open, setOpen] = useState(false);
  const [isHovering, setIsHovering] = useState(false);
  const [deleteConfirmationModalOpen, setDeleteConfirmationModalOpen] =
    useState(false);
  const { renameProject, deleteProject } = useProjectsContext();
  const [isEditing, setIsEditing] = useState(false);
  const [name, setName] = useState(project.name);

  // Keep local name in sync when project name updates elsewhere (e.g., project page rename)
  useEffect(() => {
    if (!isEditing) {
      setName(project.name);
    }
  }, [project.name, isEditing]);

  // Make project droppable
  const dropId = `project-${project.id}`;
  const { setNodeRef, isOver } = useDroppable({
    id: dropId,
    data: {
      type: "project",
      project,
    },
  });

  async function submitRename(renamedValue: string) {
    const newName = renamedValue.trim();
    if (newName === "") return;

    setName(newName);
    setIsEditing(false);
    await renameProject(project.id, newName);
  }

  // Determine which icon to show based on open/closed state and hover
  const getFolderIcon = (): React.FunctionComponent<SvgProps> => {
    if (open) {
      return isHovering
        ? SvgFolder
        : (OpenFolderIcon as React.FunctionComponent<SvgProps>);
    } else {
      return isHovering
        ? (OpenFolderIcon as React.FunctionComponent<SvgProps>)
        : SvgFolder;
    }
  };

  // Auto-expand if current chat or project in URL belongs to this project
  const currentChatId = params(SEARCH_PARAM_NAMES.CHAT_ID);
  const currentProjectId = params(SEARCH_PARAM_NAMES.PROJECT_ID);
  const containsCurrentChat = useMemo(
    () => project.chat_sessions.some((cs) => cs.id === currentChatId),
    [project.chat_sessions, currentChatId]
  );

  useEffect(() => {
    if (containsCurrentChat || currentProjectId === String(project.id)) {
      setOpen(true);
    }
  }, [containsCurrentChat, currentProjectId, project.id]);

  const handleIconClick = (e: React.MouseEvent<HTMLDivElement>) => {
    e.stopPropagation();
    setOpen((prev) => !prev);
  };

  const handleTextClick = (e: React.MouseEvent<HTMLDivElement>) => {
    e.stopPropagation();
    route({ projectId: project.id });
  };

  return (
    <>
      {/* Confirmation Modal (only for deletion) */}
      {deleteConfirmationModalOpen && (
        <ConfirmationModal
          title="Delete Project"
          icon={SvgTrash}
          onClose={() => setDeleteConfirmationModalOpen(false)}
          submit={
            <Button
              danger
              onClick={() => {
                setDeleteConfirmationModalOpen(false);
                deleteProject(project.id);
              }}
            >
              Delete
            </Button>
          }
        >
          Are you sure you want to delete this project? This action cannot be
          undone.
        </ConfirmationModal>
      )}

      {/* Project Folder */}
      <div
        ref={setNodeRef}
        className={cn(
          "transition-colors duration-200",
          isOver && "bg-background-tint-03 rounded-08"
        )}
      >
        <NavigationTab
          icon={getFolderIcon()}
          active={params(SEARCH_PARAM_NAMES.PROJECT_ID) === String(project.id)}
          onIconClick={handleIconClick}
          onIconHover={setIsHovering}
          onTextClick={handleTextClick}
          popover={
            <PopoverMenu>
              {[
                <NavigationTab
                  key="rename-project"
                  icon={SvgEdit}
                  onClick={noProp(() => setIsEditing(true))}
                >
                  Rename Project
                </NavigationTab>,
                null,
                <NavigationTab
                  key="delete-project"
                  icon={SvgTrash}
                  onClick={noProp(() => setDeleteConfirmationModalOpen(true))}
                  danger
                >
                  Delete Project
                </NavigationTab>,
              ]}
            </PopoverMenu>
          }
          renaming={isEditing}
          setRenaming={setIsEditing}
          submitRename={submitRename}
        >
          {name}
        </NavigationTab>
      </div>

      {/* Project Chat-Sessions */}
      {open &&
        project.chat_sessions.map((chatSession) => (
          <ChatButton
            key={chatSession.id}
            chatSession={chatSession}
            project={project}
            draggable
          />
        ))}
      {open && project.chat_sessions.length === 0 && (
        <div className="flex justify-center items-center">
          <Text mainUiMuted text01>
            No chat sessions yet.
          </Text>
        </div>
      )}
    </>
  );
}

export default function Projects() {
  const { projects } = useProjectsContext();
  const { toggleModal } = useChatModal();
  return (
    <>
      {projects.map((project) => (
        <ProjectFolder key={project.id} project={project} />
      ))}

      {projects.length === 0 && (
        <NavigationTab
          icon={SvgFolderPlus}
          onClick={() => toggleModal(ModalIds.CreateProjectModal, true)}
          lowlight
        >
          New Project
        </NavigationTab>
      )}
    </>
  );
}
