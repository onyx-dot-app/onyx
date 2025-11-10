"use client";

import { useRef } from "react";
import Button from "@/refresh-components/buttons/Button";
import SvgFolderPlus from "@/icons/folder-plus";
import { Modal } from "@/refresh-components/modals/NewModal";
import {
  ModalIds,
  useChatModal,
} from "@/refresh-components/contexts/ChatModalContext";
import { useProjectsContext } from "@/app/chat/projects/ProjectsContext";
import FieldInput from "@/refresh-components/inputs/FieldInput";
import { useAppRouter } from "@/hooks/appNavigation";

export default function CreateProjectModal() {
  const { createProject } = useProjectsContext();
  const { isOpen, toggleModal } = useChatModal();
  const open = isOpen(ModalIds.CreateProjectModal);
  const fieldInputRef = useRef<HTMLInputElement>(null);
  const route = useAppRouter();

  const onClose = () => toggleModal(ModalIds.CreateProjectModal, false);

  const handleOpenChange = (isOpen: boolean) => {
    if (!isOpen) {
      onClose();
    }
  };

  async function handleSubmit(e?: React.FormEvent) {
    e?.preventDefault();
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

  return (
    <Modal open={open} onOpenChange={handleOpenChange}>
      <Modal.Content
        size="sm"
        onOpenAutoFocus={(e) => {
          e.preventDefault();
          setTimeout(() => {
            fieldInputRef.current?.focus();
          }, 0);
        }}
      >
        <Modal.CloseButton />

        <Modal.Header className="flex flex-col p-4 gap-1">
          <Modal.Icon icon={SvgFolderPlus} />
          <Modal.Title>Create New Project</Modal.Title>
          <Modal.Description>
            Use projects to organize your files and chats in one place, and add
            custom instructions for ongoing work.
          </Modal.Description>
        </Modal.Header>

        <form onSubmit={handleSubmit} className="w-full">
          <Modal.Body className="flex flex-col p-4 bg-background-tint-01 w-full">
            <FieldInput
              label="Project Name"
              placeholder="What are you working on?"
              ref={fieldInputRef}
            />
          </Modal.Body>

          <Modal.Footer className="flex flex-row justify-end gap-2 p-4 w-full">
            <Button secondary onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit">Create Project</Button>
          </Modal.Footer>
        </form>
      </Modal.Content>
    </Modal>
  );
}
