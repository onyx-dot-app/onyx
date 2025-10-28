"use client";

import React, { useState, memo } from "react";
import {
  Project,
  useProjectsContext,
} from "@/app/chat/projects/ProjectsContext";
import { useDroppable } from "@dnd-kit/core";
import MenuButton from "@/refresh-components/buttons/MenuButton";
import SvgFolder from "@/icons/folder";
import SvgEdit from "@/icons/edit";
import {
  Popover,
  PopoverContent,
  PopoverMenu,
  PopoverTrigger,
} from "@/components/ui/popover";
import SvgTrash from "@/icons/trash";
import ConfirmationModal from "@/refresh-components/modals/ConfirmationModal";
import Button from "@/refresh-components/buttons/Button";
import ChatButton from "@/sections/sidebar/ChatButton";
import { useAppParams, useAppRouter } from "@/hooks/appNavigation";
import { SEARCH_PARAM_NAMES } from "@/app/chat/services/searchParams";
import { cn, noProp } from "@/lib/utils";
import { DRAG_TYPES } from "./constants";
import SidebarTab from "@/refresh-components/buttons/SidebarTab";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgMoreHorizontal from "@/icons/more-horizontal";
import { PopoverAnchor } from "@radix-ui/react-popover";
import ButtonRenaming from "./ButtonRenaming";
import { OpenFolderIcon } from "@/components/icons/CustomIcons";
import { SvgProps } from "@/icons";

interface ProjectFolderProps {
  project: Project;
}

function ProjectFolderButtonInner({ project }: ProjectFolderProps) {
  const route = useAppRouter();
  const params = useAppParams();
  const [open, setOpen] = useState(false);
  const [deleteConfirmationModalOpen, setDeleteConfirmationModalOpen] =
    useState(false);
  const { renameProject, deleteProject } = useProjectsContext();
  const [isEditing, setIsEditing] = useState(false);
  const [popoverOpen, setPopoverOpen] = useState(false);
  const [isHoveringIcon, setIsHoveringIcon] = useState(false);

  // Make project droppable
  const dropId = `project-${project.id}`;
  const { setNodeRef, isOver } = useDroppable({
    id: dropId,
    data: {
      type: DRAG_TYPES.PROJECT,
      project,
    },
  });

  const getFolderIcon = (): React.FunctionComponent<SvgProps> => {
    if (open) {
      return isHoveringIcon
        ? SvgFolder
        : (OpenFolderIcon as React.FunctionComponent<SvgProps>);
    } else {
      return isHoveringIcon
        ? (OpenFolderIcon as React.FunctionComponent<SvgProps>)
        : SvgFolder;
    }
  };

  const handleIconClick = () => {
    setOpen((prev) => !prev);
  };

  const handleTextClick = (e: React.MouseEvent<HTMLDivElement>) => {
    e.stopPropagation();
    route({ projectId: project.id });
  };

  async function handleRename(newName: string) {
    await renameProject(project.id, newName);
  }

  const popoverItems = [
    <MenuButton
      key="rename-project"
      icon={SvgEdit}
      onClick={noProp(() => setIsEditing(true))}
    >
      Rename Project
    </MenuButton>,
    null,
    <MenuButton
      key="delete-project"
      icon={SvgTrash}
      onClick={noProp(() => setDeleteConfirmationModalOpen(true))}
      danger
    >
      Delete Project
    </MenuButton>,
  ];

  return (
    <div
      ref={setNodeRef}
      className={cn(
        "transition-colors duration-200",
        isOver && "bg-background-tint-03 rounded-08"
      )}
    >
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
      <Popover onOpenChange={setPopoverOpen}>
        <PopoverAnchor>
          <SidebarTab
            leftIcon={() => (
              <IconButton
                onHover={(isHovering) => setIsHoveringIcon(isHovering)}
                icon={getFolderIcon()}
                internal
                onClick={(e) => {
                  e.stopPropagation();
                  handleIconClick();
                }}
              />
            )}
            active={
              params(SEARCH_PARAM_NAMES.PROJECT_ID) === String(project.id)
            }
            onClick={handleTextClick}
            rightChildren={
              <>
                <PopoverTrigger asChild onClick={noProp()}>
                  <div>
                    <IconButton
                      icon={SvgMoreHorizontal}
                      className={cn(
                        !popoverOpen && "hidden",
                        !isEditing && "group-hover/SidebarTab:flex"
                      )}
                      active={popoverOpen}
                      internal
                    />
                  </div>
                </PopoverTrigger>

                <PopoverContent side="right" align="end">
                  <PopoverMenu>{popoverItems}</PopoverMenu>
                </PopoverContent>
              </>
            }
          >
            {isEditing ? (
              <ButtonRenaming
                initialName={project.name}
                onRename={handleRename}
                onClose={() => setIsEditing(false)}
              />
            ) : (
              project.name
            )}
          </SidebarTab>
        </PopoverAnchor>
      </Popover>

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
    </div>
  );
}

const ProjectFolderButton = memo(ProjectFolderButtonInner);
export default ProjectFolderButton;
