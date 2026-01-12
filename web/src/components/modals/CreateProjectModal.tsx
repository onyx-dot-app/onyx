"use client";

import { useRef } from "react";
import Button from "@/refresh-components/buttons/Button";
import { useProjectsContext } from "@/app/chat/projects/ProjectsContext";
import { useKeyPress } from "@/hooks/useKeyPress";
import FieldInput from "@/refresh-components/inputs/FieldInput";
import { useAppRouter } from "@/hooks/appNavigation";
import { useModal } from "@/refresh-components/contexts/ModalContext";
import { SvgFolderPlus } from "@opal/icons";
import Modal from "@/refresh-components/Modal";

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
    <Modal open={modal.isOpen} onOpenChange={modal.toggle}>
      <Modal.Content mini>
        <Modal.Header
          icon={SvgFolderPlus}
          title="Create New Project"
          description="Use projects to organize your files and chats in one place, and add custom instructions for ongoing work."
          onClose={() => modal.toggle(false)}
        />
        <Modal.Body>
          <FieldInput
            label="Project Name"
            placeholder="What are you working on?"
            ref={fieldInputRef}
          />
        </Modal.Body>
        <Modal.Footer>
          <Button secondary onClick={() => modal.toggle(false)}>
            Cancel
          </Button>
          <Button onClick={handleSubmit}>Create Project</Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
