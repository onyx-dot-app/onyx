"use client";

import {
  FolderIcon,
  FolderIconProvider,
} from "@/lib/projects/components/ProjectFolderButton";
import CreateProjectModal from "@/lib/projects/components/CreateProjectModal";
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  Dropdown,
  EmptyMessageCard,
  SidebarTab,
  useCreateModal,
  type DropdownMenuItem,
  type DropdownRowProps,
} from "@opal/components";
import { Section } from "@opal/layouts";
import { SvgFolder, SvgFolderPlus } from "@opal/icons";
import { useAppPosition } from "@/lib/position/hooks";
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
  /** The row props from the list. Its click stays with the tabs inside. */
  rowProps: DropdownRowProps;
}
function ProjectPopoverRow({
  match,
  onNavigate,
  rowProps,
}: ProjectPopoverRowProps) {
  const appPosition = useAppPosition();
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
    appPosition.openProject(match.project.id);
  }

  return (
    <FolderIconProvider open={open} onToggle={() => setOpen((prev) => !prev)}>
      <Section
        {...rowProps}
        // A chat link's click must not also open the project.
        onClick={undefined}
        data-testid="ProjectsPopover/row"
        gap={1}
        alignItems="stretch"
        height="auto"
      >
        <SidebarTab
          icon={FolderIcon}
          // Same rule as the sidebar: while the chats are hidden, the folder
          // carries the "you are here" mark for them.
          selected={isActiveProject && (appPosition.isProject() || !open)}
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
              selected={appPosition.chat() === chatSession.id}
            >
              {chatSession.name || UNNAMED_CHAT}
            </SidebarTab>
          ))}
      </Section>
    </FolderIconProvider>
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
  const tSidebar = useTranslations("sidebar");
  const appPosition = useAppPosition();
  const createProjectModal = useCreateModal();
  const [open, setOpen] = useState(false);
  const t = useTranslations("chat");
  // The search is the caller's: it matches chat titles too, so the rows
  // are pinned past the list's own filter. The list clears the text on close.
  const [query, setQuery] = useState("");
  const matches = useProjectSearch(query);

  // Any navigation means the popover has done its job. Folding a project's
  // chats never touches the URL, so the folder icon leaves the popover open.
  useEffect(() => setOpen(false), [appPosition]);

  function handleNewProject() {
    // The modal traps focus, so the popover has to go first.
    setOpen(false);
    createProjectModal.toggle(true);
  }

  const items: DropdownMenuItem[] =
    matches.length === 0
      ? [
          {
            kind: "custom",
            id: "empty",
            disabled: true,
            pinned: true,
            render: ({ props }) => (
              <div {...props}>
                <EmptyMessageCard
                  title={t("projects.foldedPopover.empty.title")}
                  padding={2}
                />
              </div>
            ),
          },
        ]
      : matches.map((match) => ({
          kind: "custom",
          id: `project-${match.project.id}`,
          pinned: true,
          keepOpen: true,
          onActivate: () => {
            setOpen(false);
            appPosition.openProject(match.project.id);
          },
          render: ({ props }) => (
            <ProjectPopoverRow
              match={match}
              onNavigate={() => setOpen(false)}
              rowProps={props}
            />
          ),
        }));

  return (
    <>
      {/* A sibling of the popover on purpose: creating a project closes the
          popover, and a modal mounted inside it would unmount with it. */}
      <createProjectModal.Provider>
        <CreateProjectModal />
      </createProjectModal.Provider>

      <Dropdown width={20} side="right" open={open} onOpenChange={setOpen}>
        <Dropdown.Trigger asChild>
          <div data-testid="AppSidebar/projects" tabIndex={-1}>
            <SidebarTab
              icon={SvgFolder}
              type="button"
              folded
              selected={open || appPosition.isProject()}
            >
              {tSidebar("appSidebar.projects.title")}
            </SidebarTab>
          </div>
        </Dropdown.Trigger>
        <Dropdown.Data
          label={tSidebar("appSidebar.projects.title")}
          search={{
            "data-testid": "ProjectsPopover/search",
            clearButton: true,
            placeholder: t("projects.foldedPopover.search.placeholder"),
            onChange: setQuery,
            rightChildren: (
              <Button
                data-testid="ProjectsPopover/new-project"
                icon={SvgFolderPlus}
                prominence="internal"
                size="sm"
                tooltip={tSidebar("appSidebar.newProject.tooltip")}
                onClick={noProp(handleNewProject)}
              />
            ),
          }}
          items={items}
        />
      </Dropdown>
    </>
  );
}
