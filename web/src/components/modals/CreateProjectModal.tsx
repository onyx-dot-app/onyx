"use client";

import { useRef } from "react";
import Button from "@/refresh-components/buttons/Button";
import SvgFolderPlus from "@/icons/folder-plus";
import Modal from "@/refresh-components/modals/Modal";
import {
  ModalIds,
  useChatModal,
} from "@/refresh-components/contexts/ChatModalContext";
import { useProjectsContext } from "@/app/chat/projects/ProjectsContext";
import { useKeyPress } from "@/hooks/useKeyPress";
import FieldInput from "@/refresh-components/inputs/FieldInput";
import { useAppRouter } from "@/hooks/appNavigation";

export default function CreateProjectModal() {
  const { createProject } = useProjectsContext();
  const { toggleModal } = useChatModal();
  const fieldInputRef = useRef<HTMLInputElement>(null);
  const route = useAppRouter();

  async function handleSubmit() {
    if (!fieldInputRef.current) return;
    const name = fieldInputRef.current.value.trim();
    if (!name) return;

    try {
      const newProject = await createProject(name);
      route({ projectId: newProject.id });
    } catch (e) {
      console.error(`Failed to create the project ${name}`);
    }

    toggleModal(ModalIds.CreateProjectModal, false);
  }

  useKeyPress(handleSubmit, "Enter");

  return (
    <Modal
      id={ModalIds.CreateProjectModal}
      icon={SvgFolderPlus}
      title="Create New Project"
      description="Use projects to organize your files and chats in one place, and add custom instructions for ongoing work."
      xs
    >
      <div className="flex flex-col p-spacing-paragraph bg-background-tint-01">
        <FieldInput
          label="Project Name"
          placeholder="What are you working on?"
          ref={fieldInputRef}
        />
      </div>
      <div className="flex flex-row justify-end gap-spacing-interline p-spacing-paragraph">
        <Button
          secondary
          onClick={() => toggleModal(ModalIds.CreateProjectModal, false)}
        >
          Cancel
        </Button>
        <Button onClick={handleSubmit}>Create Project</Button>
      </div>
    </Modal>
  );
}
