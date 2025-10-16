"use client";

import { useEffect, useState } from "react";
import Button from "@/refresh-components/buttons/Button";
import Modal from "@/refresh-components/modals/Modal";
import {
  ModalIds,
  useChatModal,
} from "@/refresh-components/contexts/ChatModalContext";
import { useProjectsContext } from "@/app/chat/projects/ProjectsContext";
import { useKeyPress } from "@/hooks/useKeyPress";
import SvgAddLines from "@/icons/add-lines";
import { Textarea } from "@/components/ui/textarea";

export default function AddInstructionModal() {
  const { isOpen, toggleModal } = useChatModal();
  const open = isOpen(ModalIds.AddInstructionModal);
  const { currentProjectDetails, upsertInstructions } = useProjectsContext();
  const [instructionText, setInstructionText] = useState("");

  const onClose = () => toggleModal(ModalIds.AddInstructionModal, false);

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
    <Modal
      id={ModalIds.AddInstructionModal}
      icon={SvgAddLines}
      title="Set Project Instructions"
      description="Instruct specific behaviors, focus, tones, or formats for the response in this project."
      xs
    >
      <div className="bg-background-tint-01 p-spacing-paragraph">
        <Textarea
          value={instructionText}
          onChange={(e) => setInstructionText(e.target.value)}
          placeholder="Think step by step and show reasoning for complex problems. Use specific examples."
          className="min-h-[140px] border-border-01 bg-background-neutral-00"
        />
      </div>
      <div className="flex flex-row justify-end gap-spacing-interline p-spacing-paragraph">
        <Button secondary onClick={onClose}>
          Cancel
        </Button>
        <Button onClick={handleSubmit}>Save Instructions</Button>
      </div>
    </Modal>
  );
}
