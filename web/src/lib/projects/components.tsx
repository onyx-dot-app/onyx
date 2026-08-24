"use client";

import { useEffect, useState } from "react";
import { useDroppable } from "@dnd-kit/core";
import {
  Button,
  EmptyMessageCard,
  InputTypeIn,
  LineItemButton,
  Popover,
  PopoverMenu,
  SidebarTab,
  Text,
  useCreateModal,
} from "@opal/components";
import useFocusOnMount from "@opal/hooks/useFocusOnMount";
import {
  ConfirmationModalLayout,
  Section,
  useSidebarState,
} from "@opal/layouts";
import { cn } from "@opal/utils";
import type { IconFunctionComponent } from "@opal/types";
import {
  SvgEdit,
  SvgFolder,
  SvgFolderOpen,
  SvgFolderPartialOpen,
  SvgFolderPlus,
  SvgMoreHorizontal,
  SvgTrash,
} from "@opal/icons";
import ChatButton from "@/sections/sidebar/ChatButton";
import CreateProjectModal from "@/sections/modals/CreateProjectModal";
import { useAppRouter } from "@/hooks/appNavigation";
import useAppFocus from "@/hooks/useAppFocus";
import { noProp } from "@/lib/utils";
import { UNNAMED_CHAT } from "@/lib/constants";
import { DRAG_TYPES } from "@/lib/sidebar/constants";
import { useActiveProject, useProjectSearch } from "@/lib/projects/hooks";
import type { Project, ProjectSearchMatch } from "@/lib/projects/types";
import { useProjectsContext } from "@/providers/ProjectsContext";
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
 * The folder glyph for a project row: open or closed by fold state, previewing
 * the partial-open folder on hover, and toggling the fold on click without
 * letting the click reach the row underneath.
 *
 * After a click the preview stays off until the pointer leaves, so the icon does
 * not preview the state the user just left.
 *
 * Shared by both project rows so the glyph cannot drift between them. The state
 * lives here and the returned render function is stateless on purpose:
 * `SidebarTab` reconciles `icon` by function identity, so a stateful component
 * would remount whenever `open` changed and reset the preview mid-hover.
 */
function useFolderIcon(
  open: boolean,
  onToggle: () => void
): IconFunctionComponent {
  const [hovering, setHovering] = useState(false);
  const [previewEnabled, setPreviewEnabled] = useState(true);

  const Glyph =
    hovering && previewEnabled
      ? SvgFolderPartialOpen
      : open
        ? SvgFolderOpen
        : SvgFolder;

  return () => (
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

/**
 * A project row inside the folded sidebar's Projects popover: the folder tab
 * and, when open, the project's chats.
 *
 * Deliberately narrower than `ProjectFolderButton` — the popover navigates, it
 * does not manage. There is no drop target, because a popover has nothing to
 * drag from, and no rename or delete menu.
 */
interface ProjectPopoverRowProps {
  match: ProjectSearchMatch;
  onNavigate: () => void;
}
function ProjectPopoverRow({ match, onNavigate }: ProjectPopoverRowProps) {
  const route = useAppRouter();
  const appFocus = useAppFocus();
  const activeProject = useActiveProject();
  const isActiveProject = activeProject?.id === match.project.id;
  const [open, setOpen] = useState(isActiveProject);
  const folderIcon = useFolderIcon(open, () => setOpen((prev) => !prev));

  // Unfold the project the user is inside, and any project listed because one
  // of its chats matched the search — otherwise the reason it is listed stays
  // hidden. Only ever opens, so folding it by hand sticks.
  useEffect(() => {
    if (isActiveProject || match.chatMatched) setOpen(true);
  }, [isActiveProject, match.chatMatched]);

  function handleClick() {
    // Navigation closes the popover on its own, but re-selecting the project
    // you are already inside leaves the URL alone.
    onNavigate();
    route({ projectId: match.project.id });
  }

  return (
    <div data-testid="ProjectsPopover/row" className="flex flex-col gap-1">
      <SidebarTab
        icon={folderIcon}
        // Same rule as the sidebar: while the chats are hidden, the folder
        // carries the "you are here" mark for them.
        selected={isActiveProject && (appFocus.isProject() || !open)}
        onClick={noProp(handleClick)}
      >
        {match.project.name}
      </SidebarTab>
      {open &&
        match.chatSessions.map((chatSession) => (
          <SidebarTab
            key={chatSession.id}
            // `nested` supplies the indent that lines a chat up under its
            // project, so the row needs no icon of its own.
            nested
            href={`/app?chatId=${chatSession.id}`}
            onClick={onNavigate}
            selected={appFocus.getId() === chatSession.id}
          >
            {chatSession.name || UNNAMED_CHAT}
          </SidebarTab>
        ))}
    </div>
  );
}

/**
 * The folded sidebar's Projects entry.
 *
 * Folded, the sidebar has no room for the projects tree, and a project's chats
 * are reachable nowhere else — Recents excludes them. So the tab hands the whole
 * tree to a popover: search, new project, and every project with its chats.
 *
 * Resolves the sidebar's fold state itself and renders nothing when unfolded, so
 * callers can mount it unconditionally.
 */
export function FoldedProjectsPopover() {
  const { folded } = useSidebarState();
  const appFocus = useAppFocus();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const matches = useProjectSearch(query);
  const focusOnMount = useFocusOnMount<HTMLInputElement>();
  const createProjectModal = useCreateModal();

  // Any navigation means the popover has done its job. Folding a project's
  // chats never touches the URL, so the folder icon leaves the popover open.
  useEffect(() => setOpen(false), [appFocus]);

  function handleOpenChange(nextOpen: boolean) {
    setOpen(nextOpen);
    // Every opening starts from a clean slate.
    if (!nextOpen) setQuery("");
  }

  function handleNewProject() {
    // The modal traps focus, so the popover has to go first.
    setOpen(false);
    createProjectModal.toggle(true);
  }

  if (!folded) return null;

  return (
    <>
      {/* A sibling of the popover on purpose: creating a project closes the
          popover, and a modal mounted inside it would unmount with it. */}
      <createProjectModal.Provider>
        <CreateProjectModal />
      </createProjectModal.Provider>

      <Popover open={open} onOpenChange={handleOpenChange}>
        <Popover.Trigger asChild>
          {/* `SidebarTab` does not forward refs, so Radix anchors to this div. */}
          <div data-testid="AppSidebar/projects">
            <SidebarTab
              icon={SvgFolder}
              type="button"
              folded
              selected={open || appFocus.isProject()}
            >
              Projects
            </SidebarTab>
          </div>
        </Popover.Trigger>

        <Popover.Content
          data-testid="ProjectsPopover"
          side="right"
          align="start"
          width="lg"
        >
          <Section flexDirection="row" padding={0} gap={0}>
            <InputTypeIn
              data-testid="ProjectsPopover/search"
              searchIcon
              clearButton
              ref={focusOnMount}
              variant="internal"
              placeholder="Search projects..."
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              rightChildren={
                <Button
                  data-testid="ProjectsPopover/new-project"
                  icon={SvgFolderPlus}
                  prominence="internal"
                  size="sm"
                  tooltip="New Project"
                  onClick={noProp(handleNewProject)}
                />
              }
            />
          </Section>

          <PopoverMenu>
            {matches.length === 0
              ? [
                  <EmptyMessageCard
                    key="empty"
                    title="No projects found"
                    padding={2}
                  />,
                ]
              : matches.map((match) => (
                  <ProjectPopoverRow
                    key={match.project.id}
                    match={match}
                    onNavigate={() => setOpen(false)}
                  />
                ))}
          </PopoverMenu>
        </Popover.Content>
      </Popover>
    </>
  );
}
