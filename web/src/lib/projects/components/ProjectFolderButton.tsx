"use client";

import React, {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
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
import { useProjectsContext } from "@/lib/projects/providers";
import ButtonRenaming from "@/refresh-components/buttons/ButtonRenaming";

/**
 * What the folder glyph needs from the row it sits in.
 *
 * It arrives by context rather than as props because `SidebarTab` renders
 * `icon` as a component type and passes it nothing of ours.
 */
interface FolderIconState {
  open: boolean;
  onToggle: () => void;
}
const FolderIconContext = createContext<FolderIconState | null>(null);

/**
 * The folder glyph for a project row: open or closed by fold state, previewing
 * the partial-open folder on hover, and toggling the fold on click without
 * letting the click reach the row underneath.
 *
 * After a click the preview stays off until the pointer leaves, so the icon does
 * not preview the state the user just left.
 *
 * Declared once, at module scope, and that is the point. `SidebarTab` renders
 * `icon` as a component type, so handing it a fresh function each render would
 * be handing it a new type: React tears the button down and builds another,
 * losing keyboard focus the moment you press it and dropping the hover preview
 * on any unrelated re-render. Hover state lives here, where it re-renders
 * without changing type, and the fold state comes through the context.
 */
export function FolderIcon() {
  const state = useContext(FolderIconContext);
  const [hovering, setHovering] = useState(false);
  const [previewEnabled, setPreviewEnabled] = useState(true);

  if (!state) return null;
  const { open, onToggle } = state;

  const Glyph =
    hovering && previewEnabled
      ? SvgFolderPartialOpen
      : open
        ? SvgFolderOpen
        : SvgFolder;

  return (
    /* Deliberately not an Opal `Button`. This was a div, promoted to a button
       for its semantics alone — focusable, with a role and keyboard handling.
       It wants none of the chrome Opal's Button brings: focus ring, padding,
       sizing, interaction styling. It is a bare glyph. */
    <button
      type="button"
      data-testid="ProjectFolderIcon"
      // The glyph carries no text, so the control needs its own name and state.
      aria-label={open ? "Collapse project" : "Expand project"}
      aria-expanded={open}
      /* Above the tab's click overlay. `SidebarTab` lays an absolute
         `z-99` control over the whole row whenever it has an `onClick`, and a
         statically positioned element can never paint above it — so without
         this the click lands on the row and navigates instead of folding.
         `rightChildren` solves the same problem the same way. */
      className="relative z-100 p-0 cursor-pointer"
      onMouseEnter={() => setHovering(true)}
      onMouseLeave={() => {
        setHovering(false);
        setPreviewEnabled(true);
      }}
      onClick={noProp(() => {
        setPreviewEnabled(false);
        onToggle();
      })}
    >
      <Glyph size={16} className="text-text-03" />
    </button>
  );
}

/**
 * Wrap the row whose `SidebarTab` renders {@link FolderIcon}, so the glyph can
 * read the fold state without the icon component changing identity.
 */
export interface FolderIconProviderProps extends FolderIconState {
  children: React.ReactNode;
}
export function FolderIconProvider({
  open,
  onToggle,
  children,
}: FolderIconProviderProps) {
  const value = useMemo(() => ({ open, onToggle }), [open, onToggle]);
  return (
    <FolderIconContext.Provider value={value}>
      {children}
    </FolderIconContext.Provider>
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
      rounding={2}
      icon={SvgEdit}
      title="Rename Project"
      onClick={noProp(() => setIsEditing(true))}
    />,
    null,
    <LineItemButton
      key="delete-project"
      sizePreset="main-ui"
      rounding={2}
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
      <FolderIconProvider open={open} onToggle={() => setOpen((prev) => !prev)}>
        <Popover onOpenChange={setPopoverOpen}>
          <Popover.Anchor>
            <SidebarTab
              icon={FolderIcon}
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
      </FolderIconProvider>

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
