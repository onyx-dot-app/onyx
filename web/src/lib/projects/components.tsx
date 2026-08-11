"use client";

import React, { useEffect, useState } from "react";
import { useDroppable } from "@dnd-kit/core";
import {
  Button,
  LineItemButton,
  Popover,
  PopoverMenu,
  SidebarTab,
  Text,
} from "@opal/components";
import { ConfirmationModalLayout } from "@opal/layouts";
import { cn } from "@opal/utils";
import type { IconProps } from "@opal/types";
import {
  SvgEdit,
  SvgFolder,
  SvgFolderOpen,
  SvgFolderPartialOpen,
  SvgMoreHorizontal,
  SvgTrash,
} from "@opal/icons";
import ChatButton from "@/sections/sidebar/ChatButton";
import { useAppRouter } from "@/hooks/appNavigation";
import useAppFocus from "@/hooks/useAppFocus";
import { noProp } from "@/lib/utils";
import { DRAG_TYPES } from "@/lib/sidebar/constants";
import { useActiveProject } from "@/lib/projects/hooks";
import type { Project } from "@/lib/projects/types";
import { useProjectsContext } from "@/providers/ProjectsContext";
import Truncated from "@/refresh-components/texts/Truncated";
import ButtonRenaming from "@/refresh-components/buttons/ButtonRenaming";

/**
 * The active project's name for the app header, so a chat inside a project says
 * which one. Nothing else surfaces this — `projectId` is dropped from the URL
 * once a chat opens (see `PARAMS_TO_SKIP` in `app/app/services/lib.tsx`).
 *
 * Chats only. The project page already names itself in `ProjectContextPanel`,
 * so repeating it in the header would be noise.
 *
 * Resolves the active project itself and renders nothing when there is none, so
 * callers can mount it unconditionally.
 *
 * A label, not navigation — the header states where you are and nothing more.
 */
export function ActiveProjectBreadcrumb() {
  const appFocus = useAppFocus();
  const project = useActiveProject();

  if (!appFocus.isChat() || !project) return null;

  return (
    <div className="p-2 flex flex-row items-center gap-0.5">
      <div className="p-0.5">
        <SvgFolder className="text-text-03" size={16} />
      </div>

      <div className="px-1">
        <Text nowrap as="p">
          {project.name}
        </Text>
      </div>
    </div>
  );
}

/**
 * A project's sidebar row: the folder tab itself plus, when unfolded, the
 * project's chats. Doubles as a drop target for dragging a chat into it.
 */
export interface ProjectFolderButtonProps {
  project: Project;
}
export function ProjectFolderButton({ project }: ProjectFolderButtonProps) {
  const route = useAppRouter();
  const activeSidebar = useAppFocus();
  const activeProject = useActiveProject();
  const isActiveProject = activeProject?.id === project.id;
  const [open, setOpen] = useState(isActiveProject);
  const [deleteConfirmationModalOpen, setDeleteConfirmationModalOpen] =
    useState(false);
  const { renameProject, deleteProject } = useProjectsContext();
  const [isEditing, setIsEditing] = useState(false);
  const [popoverOpen, setPopoverOpen] = useState(false);
  const [isHoveringIcon, setIsHoveringIcon] = useState(false);
  const [allowHoverEffect, setAllowHoverEffect] = useState(true);

  // Unfold whichever project the user moves into, so its chats are visible on
  // arrival. Only ever opens — folding it again while still inside the project
  // sticks, because the effect does not re-run until the active project changes.
  useEffect(() => {
    if (isActiveProject) setOpen(true);
  }, [isActiveProject]);

  // Make project droppable
  const dropId = `project-${project.id}`;
  const { setNodeRef, isOver } = useDroppable({
    id: dropId,
    data: {
      type: DRAG_TYPES.PROJECT,
      project,
    },
  });

  function getFolderIcon(): React.FunctionComponent<IconProps> {
    if (open) {
      return SvgFolderOpen;
    } else {
      return isHoveringIcon && allowHoverEffect
        ? SvgFolderPartialOpen
        : SvgFolder;
    }
  }

  function handleIconClick() {
    setOpen((prev) => !prev);
    setAllowHoverEffect(false);
  }

  function handleIconHover(hovering: boolean) {
    setIsHoveringIcon(hovering);
    // Re-enable hover effects when cursor leaves the icon
    if (!hovering) {
      setAllowHoverEffect(true);
    }
  }

  function handleTextClick() {
    route({ projectId: project.id });
  }

  async function handleRename(newName: string) {
    await renameProject(project.id, newName);
  }

  const popoverItems = [
    <LineItemButton
      key="rename-project"
      sizePreset="main-ui"
      rounding="sm"
      icon={SvgEdit}
      title="Rename Project"
      onClick={noProp(() => setIsEditing(true))}
    />,
    null,
    <LineItemButton
      key="delete-project"
      sizePreset="main-ui"
      rounding="sm"
      color="danger"
      icon={SvgTrash}
      title="Delete Project"
      onClick={noProp(() => setDeleteConfirmationModalOpen(true))}
    />,
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
        <ConfirmationModalLayout
          title="Delete Project"
          icon={SvgTrash}
          onClose={() => setDeleteConfirmationModalOpen(false)}
          submit={
            <Button
              variant="danger"
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
        </ConfirmationModalLayout>
      )}

      {/* Project Folder */}
      <Popover onOpenChange={setPopoverOpen}>
        <Popover.Anchor>
          <SidebarTab
            icon={() => (
              <Button
                onMouseEnter={() => handleIconHover(true)}
                onMouseLeave={() => handleIconHover(false)}
                icon={getFolderIcon()}
                prominence="tertiary"
                size="sm"
                onClick={noProp(handleIconClick)}
              />
            )}
            // Folded, the project's chats are hidden — and a project chat
            // appears nowhere else in the sidebar (Recents excludes them), so
            // the folder itself has to carry the "you are here" mark.
            selected={isActiveProject && (activeSidebar.isProject() || !open)}
            onClick={noProp(handleTextClick)}
            rightChildren={
              <>
                <Popover.Trigger asChild onClick={noProp()}>
                  <div
                    className={cn(
                      !popoverOpen && "hidden",
                      !isEditing && "group-hover/SidebarTab:flex"
                    )}
                  >
                    <Button
                      icon={SvgMoreHorizontal}
                      prominence="internal"
                      size="sm"
                      interaction={popoverOpen ? "hover" : "rest"}
                    />
                  </div>
                </Popover.Trigger>

                <Popover.Content side="right" align="end" width="md">
                  <PopoverMenu>{popoverItems}</PopoverMenu>
                </Popover.Content>
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
              <Truncated text03>{project.name}</Truncated>
            )}
          </SidebarTab>
        </Popover.Anchor>
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
