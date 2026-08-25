"use client";

import { useFolderIcon } from "@/lib/projects/components/useFolderIcon";
import { useEffect, useState } from "react";
import { useDroppable } from "@dnd-kit/core";
import {
  Button,
  LineItemButton,
  Popover,
  PopoverMenu,
  SidebarTab,
} from "@opal/components";
import { ConfirmationModalLayout } from "@opal/layouts";
import { cn } from "@opal/utils";
import { SvgEdit, SvgMoreHorizontal, SvgTrash } from "@opal/icons";
import ChatButton from "@/sections/sidebar/ChatButton";
import { useAppRouter } from "@/hooks/appNavigation";
import useAppFocus from "@/hooks/useAppFocus";
import { noProp } from "@/lib/utils";
import { DRAG_TYPES } from "@/lib/sidebar/constants";
import { useActiveProject } from "@/lib/projects/hooks";
import type { Project } from "@/lib/projects/types";
import { useProjectsContext } from "@/lib/projects/providers";
import ButtonRenaming from "@/refresh-components/buttons/ButtonRenaming";

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
  const folderIcon = useFolderIcon(open, () => setOpen((prev) => !prev));

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
            icon={folderIcon}
            // Folded, the project's chats are hidden — and a project chat
            // appears nowhere else in the sidebar (Recents excludes them), so
            // the folder itself has to carry the "you are here" mark.
            selected={isActiveProject && (activeSidebar.isProject() || !open)}
            /* While renaming, drop the click target so the input stays usable. */
            onClick={isEditing ? undefined : noProp(handleTextClick)}
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
              project.name
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
