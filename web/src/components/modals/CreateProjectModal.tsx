"use client";

import { useRef } from "react";
import Button from "@/refresh-components/buttons/Button";
import SvgFolderPlus from "@/icons/folder-plus";
import ModalContent from "@/refresh-components/modals/ModalContent";
import { useProjectsContext } from "@/app/chat/projects/ProjectsContext";
import { useKeyPress } from "@/hooks/useKeyPress";
import FieldInput from "@/refresh-components/inputs/FieldInput";
import { useAppRouter } from "@/hooks/appNavigation";
import { useModal } from "@/refresh-components/contexts/ModalContext";

export default function CreateProjectModal() {
  const { createProject } = useProjectsContext();
  const { toggle } = useModal();
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

    toggle(false);
  }

  useKeyPress(handleSubmit, "Enter");

  return (
    <ModalContent
      icon={SvgFolderPlus}
      title="Create New Project"
      description="Use projects to organize your files and chats in one place, and add custom instructions for ongoing work."
    >
      <div className="flex flex-col p-spacing-paragraph bg-background-tint-01">
        <FieldInput
          label="Project Name"
          placeholder="What are you working on?"
          ref={fieldInputRef}
        />
      </div>
      <div className="flex flex-row justify-end gap-spacing-interline p-spacing-paragraph">
        <Button secondary onClick={() => toggle(false)}>
          Cancel
        </Button>
        <Button onClick={handleSubmit}>Create Project</Button>
      </div>
    </ModalContent>
  );
}
