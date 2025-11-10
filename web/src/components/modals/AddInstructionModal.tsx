"use client";

import { useEffect, useState, useRef } from "react";
import Button from "@/refresh-components/buttons/Button";
import { Modal } from "@/refresh-components/modals/NewModal";
import {
  ModalIds,
  useChatModal,
} from "@/refresh-components/contexts/ChatModalContext";
import { useProjectsContext } from "@/app/chat/projects/ProjectsContext";
import SvgAddLines from "@/icons/add-lines";
import { Textarea } from "@/components/ui/textarea";

export default function AddInstructionModal() {
  const { isOpen, toggleModal } = useChatModal();
  const open = isOpen(ModalIds.AddInstructionModal);
  const { currentProjectDetails, upsertInstructions } = useProjectsContext();
  const [instructionText, setInstructionText] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const onClose = () => toggleModal(ModalIds.AddInstructionModal, false);

  const handleOpenChange = (isOpen: boolean) => {
    if (!isOpen) {
      onClose();
    }
  };

  useEffect(() => {
    if (open) {
      const preset = currentProjectDetails?.project?.instructions ?? "";
      setInstructionText(preset);
    }
  }, [open, currentProjectDetails?.project?.instructions]);

  async function handleSubmit() {
    const value = instructionText.trim();
    try {
      await upsertInstructions(value);
    } catch (e) {
      console.error("Failed to save instructions", e);
    }
    toggleModal(ModalIds.AddInstructionModal, false);
  }

  return (
    <Modal open={open} onOpenChange={handleOpenChange}>
      <Modal.Content
        size="sm"
        onOpenAutoFocus={(e) => {
          e.preventDefault();
          setTimeout(() => {
            textareaRef.current?.focus();
          }, 0);
        }}
      >
        <Modal.CloseButton />

        <Modal.Header className="flex flex-col p-4 gap-1">
          <Modal.Icon icon={SvgAddLines} />
          <Modal.Title>Set Project Instructions</Modal.Title>
          <Modal.Description>
            Instruct specific behaviors, focus, tones, or formats for the
            response in this project.
          </Modal.Description>
        </Modal.Header>

        <Modal.Body className="bg-background-tint-01 p-4">
          <Textarea
            ref={textareaRef}
            value={instructionText}
            onChange={(e) => setInstructionText(e.target.value)}
            placeholder="Think step by step and show reasoning for complex problems. Use specific examples."
            className="min-h-[140px] border-border-01 bg-background-neutral-00"
          />
        </Modal.Body>

        <Modal.Footer className="flex flex-row justify-end gap-2 p-4">
          <Button secondary onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={handleSubmit}>Save Instructions</Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
