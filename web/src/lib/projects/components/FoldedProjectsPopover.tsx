"use client";

import {
  FolderIcon,
  FolderIconProvider,
} from "@/lib/projects/components/ProjectFolderButton";
import CreateProjectModal from "@/lib/projects/components/CreateProjectModal";
import { useEffect, useState } from "react";
import {
  Button,
  EmptyMessageCard,
  InputTypeIn,
  Popover,
  PopoverMenu,
  SidebarTab,
  useCreateModal,
} from "@opal/components";
import { useFocusOnMount } from "@opal/hooks";
import { Section } from "@opal/layouts";
import { SvgFolder, SvgFolderPlus } from "@opal/icons";
import { useAppRouter } from "@/hooks/appNavigation";
import useAppFocus from "@/hooks/useAppFocus";
import { noProp } from "@/lib/utils";
import { UNNAMED_CHAT } from "@/lib/constants";
import { usePinChatAgent } from "@/lib/agents/hooks";
import { useActiveProject, useProjectSearch } from "@/lib/projects/hooks";
import type { Project, ProjectSearchMatch } from "@/lib/projects/types";

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
  const pinChatAgent = usePinChatAgent();
  const activeProject = useActiveProject();
  const isActiveProject = activeProject?.id === match.project.id;
  const [open, setOpen] = useState(isActiveProject);

  // A project listed because one of its chats matched has to show that chat —
  // a hit you cannot see is no hit at all. Only ever opens, so folding it by
  // hand sticks. The project you are inside needs nothing here: navigating
  // closes the popover, so unfolding on the way out would show nobody
  // anything.
  useEffect(() => {
    if (match.chatMatched) setOpen(true);
  }, [match.chatMatched]);

  function handleClick() {
    // Navigation closes the popover on its own, but re-selecting the project
    // you are already inside leaves the URL alone.
    onNavigate();
    route({ projectId: match.project.id });
  }

  return (
    <FolderIconProvider open={open} onToggle={() => setOpen((prev) => !prev)}>
      <Section
        data-testid="ProjectsPopover/row"
        gap={1}
        alignItems="stretch"
        height="auto"
      >
        <SidebarTab
          icon={FolderIcon}
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
              // Opening a chat pins its agent, the same as the sidebar's own
              // rows — the popover is another way in, not a different one.
              onClick={() => {
                pinChatAgent(chatSession);
                onNavigate();
              }}
              selected={appFocus.getId() === chatSession.id}
            >
              {chatSession.name || UNNAMED_CHAT}
            </SidebarTab>
          ))}
      </Section>
    </FolderIconProvider>
  );
}

/**
 * What the folded sidebar's Projects popover holds: the search field, the New
 * Project button, and every project with its chats.
 *
 * Its own component so the search term is its own state. Radix unmounts the
 * popover's content on close, so the term goes with it and every opening starts
 * from a clean slate, without anything having to remember to clear it.
 */
interface FoldedProjectsPopoverContentProps {
  onNavigate: () => void;
  onNewProject: () => void;
}
function FoldedProjectsPopoverContent({
  onNavigate,
  onNewProject,
}: FoldedProjectsPopoverContentProps) {
  const [query, setQuery] = useState("");
  const matches = useProjectSearch(query);
  const focusOnMount = useFocusOnMount<HTMLInputElement>();

  return (
    <>
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
              onClick={noProp(onNewProject)}
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
                onNavigate={onNavigate}
              />
            ))}
      </PopoverMenu>
    </>
  );
}

/**
 * The folded sidebar's Projects entry.
 *
 * Folded, the sidebar has no room for the projects tree, and a project's chats
 * are reachable nowhere else — Recents excludes them. So the tab hands the whole
 * tree to a popover: search, new project, and every project with its chats.
 *
 * Mounted only while the sidebar is folded, so `open` lives here: unfolding
 * takes the popover and its state together, and refolding starts closed. The
 * search term inside it works the same way, one level down.
 */
export function FoldedProjectsPopover() {
  const appFocus = useAppFocus();
  const createProjectModal = useCreateModal();
  const [open, setOpen] = useState(false);

  // Any navigation means the popover has done its job. Folding a project's
  // chats never touches the URL, so the folder icon leaves the popover open.
  useEffect(() => setOpen(false), [appFocus]);

  function handleNewProject() {
    // The modal traps focus, so the popover has to go first.
    setOpen(false);
    createProjectModal.toggle(true);
  }

  return (
    <>
      {/* A sibling of the popover on purpose: creating a project closes the
          popover, and a modal mounted inside it would unmount with it. */}
      <createProjectModal.Provider>
        <CreateProjectModal />
      </createProjectModal.Provider>

      <Popover open={open} onOpenChange={setOpen}>
        <Popover.Trigger asChild>
          <div data-testid="AppSidebar/projects" tabIndex={-1}>
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
          <FoldedProjectsPopoverContent
            onNavigate={() => setOpen(false)}
            onNewProject={handleNewProject}
          />
        </Popover.Content>
      </Popover>
    </>
  );
}
