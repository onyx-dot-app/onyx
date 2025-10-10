"use client";

import React, { useState } from "react";
import {
  Project,
  useProjectsContext,
} from "@/app/chat/projects/ProjectsContext";
import NavigationTab from "@/refresh-components/buttons/NavigationTab";
import SvgFolder from "@/icons/folder";
import SvgEdit from "@/icons/edit";
import { PopoverMenu } from "@/components/ui/popover";
import SvgTrash from "@/icons/trash";
import ConfirmationModalContent from "@/refresh-components/modals/ConfirmationModalContent";
import Button from "@/refresh-components/buttons/Button";
import { ChatButton } from "@/sections/sidebar/AppSidebar";
import { useAppParams, useAppRouter } from "@/hooks/appNavigation";
import { SEARCH_PARAM_NAMES } from "@/app/chat/services/searchParams";
import { noProp } from "@/lib/utils";
import { createModalProvider } from "@/refresh-components/contexts/ModalContext";

export interface ProjectFolderProps {
  project: Project;
}

export default function ProjectFolder({ project }: ProjectFolderProps) {
  const {
    toggle: toggleDeleteConfirmationModal,
    ModalProvider: DeleteConfirmationModalProvider,
  } = createModalProvider();

  const route = useAppRouter();
  const params = useAppParams();
  const [open, setOpen] = useState(false);
  const { renameProject, deleteProject } = useProjectsContext();
  const [isEditing, setIsEditing] = useState(false);
  const [name, setName] = useState(project.name);

  async function submitRename(renamedValue: string) {
    const newName = renamedValue.trim();
    if (newName === "") return;

    setName(newName);
    setIsEditing(false);
    await renameProject(project.id, newName);
  }

  return (
    <>
      <DeleteConfirmationModalProvider>
        <ConfirmationModalContent
          title="Delete Project"
          icon={SvgTrash}
          submit={
            <Button
              danger
              onClick={() => {
                toggleDeleteConfirmationModal(false);
                deleteProject(project.id);
              }}
            >
              Delete
            </Button>
          }
        >
          Are you sure you want to delete this project? This action cannot be
          undone.
        </ConfirmationModalContent>
      </DeleteConfirmationModalProvider>

      {/* Project Folder */}
      <NavigationTab
        icon={SvgFolder}
        active={params(SEARCH_PARAM_NAMES.PROJECT_ID) === String(project.id)}
        onClick={() => {
          setOpen((prev) => !prev);
          route({ projectId: project.id });
        }}
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
                onClick={noProp(() => toggleDeleteConfirmationModal(true))}
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

      {/* Project Chat-Sessions */}
      {open &&
        project.chat_sessions.map((chatSession) => (
          <ChatButton
            key={chatSession.id}
            chatSession={chatSession}
            project={project}
          />
        ))}
    </>
  );
}
