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
import ConfirmationModal from "@/refresh-components/modals/ConfirmationModal";
import Button from "@/refresh-components/buttons/Button";
import { ChatButton } from "@/sections/sidebar/AppSidebar";
import { useAppParams, useAppRouter } from "@/hooks/appNavigation";
import SvgFolderPlus from "@/icons/folder-plus";
import { ModalIds, useModal } from "@/refresh-components/contexts/ModalContext";
import { SEARCH_PARAM_NAMES } from "@/app/chat/services/searchParams";
import { noProp } from "@/lib/utils";

interface ProjectFolderProps {
  project: Project;
}

function ProjectFolder({ project }: ProjectFolderProps) {
  const route = useAppRouter();
  const params = useAppParams();
  const [open, setOpen] = useState(false);
  const [deleteConfirmationModalOpen, setDeleteConfirmationModalOpen] =
    useState(false);
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

export default function Projects() {
  const { projects } = useProjectsContext();
  const { toggleModal } = useModal();
  return (
    <>
      {projects.map((project) => (
        <ProjectFolder key={project.id} project={project} />
      ))}

      <NavigationTab
        icon={SvgFolderPlus}
        onClick={() => toggleModal(ModalIds.CreateProjectModal, true)}
        lowlight
      >
        New Project
      </NavigationTab>
    </>
  );
}
