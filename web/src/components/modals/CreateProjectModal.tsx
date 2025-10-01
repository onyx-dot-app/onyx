"use client";

import { useRef } from "react";
import Button from "@/refresh-components/buttons/Button";
import SvgFolderPlus from "@/icons/folder-plus";
import CoreModal from "@/refresh-components/modals/CoreModal";
import { ModalIds, useModal } from "@/refresh-components/contexts/ModalContext";
import { useProjectsContext } from "@/app/chat/projects/ProjectsContext";
import { useEscape, useKeyPress } from "@/hooks/useKeyPress";
import FieldInput from "@/refresh-components/inputs/FieldInput";
import { useAppRouter } from "@/hooks/appNavigation";
import Text from "@/refresh-components/Text";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgX from "@/icons/x";

export default function CreateProjectModal() {
  const { createProject } = useProjectsContext();
  const { toggleModal, isOpen } = useModal();
  const fieldInputRef = useRef<HTMLInputElement>(null);
  const route = useAppRouter();
  const onClose = () => toggleModal(ModalIds.CreateProjectModal, false);
  const open = isOpen(ModalIds.CreateProjectModal);

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

  useKeyPress(handleSubmit, "Enter", open);
  useEscape(onClose, open);

  if (!open) return null;

  return (
    <CoreModal
      className="w-[32rem] rounded-16 border flex flex-col bg-background-tint-00"
      onClickOutside={() => onClose()}
    >
      <div className="flex flex-col items-center justify-center gap-spacing-interline p-spacing-paragraph">
        <div className="h-[1.5rem] flex flex-row justify-between items-center w-full">
          <SvgFolderPlus className="w-[1.5rem] h-[1.5rem] stroke-text-04" />
          <IconButton icon={SvgX} internal onClick={onClose} />
        </div>
        <Text headingH3 text04 className="w-full text-left">
          Create New Project
        </Text>
        <Text text03>
          Use projects to organize your files and chats in one place, and add
          custom instructions for ongoing work.
        </Text>
      </div>
      <div className="bg-background-tint-01 p-spacing-paragraph">
        <FieldInput
          label="Project Name"
          placeholder="What are you working on?"
          ref={fieldInputRef}
        />
      </div>
      <div className="flex flex-row justify-end gap-spacing-interline p-spacing-paragraph">
        <Button secondary onClick={onClose}>
          Cancel
        </Button>
        <Button onClick={handleSubmit}>Create Project</Button>
      </div>
    </CoreModal>
  );
}
