"use client";

import { useState } from "react";
import Button from "@/refresh-components/buttons/Button";
import { useProjectsContext } from "@/app/app/projects/ProjectsContext";
import { useKeyPress } from "@/hooks/useKeyPress";
import * as InputLayouts from "@/layouts/input-layouts";
import { useAppRouter } from "@/hooks/appNavigation";
import { useModal } from "@/refresh-components/contexts/ModalContext";
import { SvgFolderPlus } from "@opal/icons";
import Modal from "@/refresh-components/Modal";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import { usePopup } from "@/components/admin/connectors/Popup";

export default function CreateProjectModal() {
  const { createProject } = useProjectsContext();
  const modal = useModal();
  const route = useAppRouter();
  const [projectName, setProjectName] = useState("");
  const { popup, setPopup } = usePopup();

  async function handleSubmit() {
    const name = projectName.trim();
    if (!name) return;

    try {
      const newProject = await createProject(name);
      route({ projectId: newProject.id });
      modal.toggle(false);
    } catch (e) {
      setPopup({
        type: "error",
        message: `Failed to create the project ${name}`,
      });
    }
  }

  useKeyPress(handleSubmit, "Enter");

  return (
    <>
      {popup}

      <Modal open={modal.isOpen} onOpenChange={modal.toggle}>
        <Modal.Content width="sm">
          <Modal.Header
            icon={SvgFolderPlus}
            title="Create New Project"
            description="Use projects to organize your files and chats in one place, and add custom instructions for ongoing work."
            onClose={() => modal.toggle(false)}
          />
          <Modal.Body>
            <InputLayouts.Vertical title="Project Name">
              <InputTypeIn
                value={projectName}
                onChange={(e) => setProjectName(e.target.value)}
                placeholder="What are you working on?"
                showClearButton
              />
            </InputLayouts.Vertical>
          </Modal.Body>
          <Modal.Footer>
            <Button secondary onClick={() => modal.toggle(false)}>
              Cancel
            </Button>
            <Button onClick={handleSubmit}>Create Project</Button>
          </Modal.Footer>
        </Modal.Content>
      </Modal>
    </>
  );
}
