"use client";

import { useRef } from "react";
import Button from "@/refresh-components/buttons/Button";
import SvgFolderPlus from "@/icons/folder-plus";
import Modal from "@/refresh-components/modals/Modal";
import { useProjectsContext } from "@/app/chat/projects/ProjectsContext";
import { useKeyPress } from "@/hooks/useKeyPress";
import FieldInput from "@/refresh-components/inputs/FieldInput";
import { useAppRouter } from "@/hooks/appNavigation";
import { useModal } from "@/refresh-components/contexts/ModalContext";

export default function CreateProjectModal() {
  const { createProject } = useProjectsContext();
  const modal = useModal();
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

    modal.toggle(false);
  }

  useKeyPress(handleSubmit, "Enter");

  return (
    <Modal
      icon={SvgFolderPlus}
      title="Create New Project"
      description="Use projects to organize your files and chats in one place, and add custom instructions for ongoing work."
      mini
    >
      <div className="flex flex-col p-4 bg-background-tint-01">
        <FieldInput
          label="Project Name"
          placeholder="What are you working on?"
          ref={fieldInputRef}
        />
      </div>
      <div className="flex flex-row justify-end gap-2 p-4">
        <Button secondary onClick={() => modal.toggle(false)}>
          Cancel
        </Button>
        <Button onClick={handleSubmit}>Create Project</Button>
      </div>
    </Modal>
  );
}
