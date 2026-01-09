"use client";

import { useEffect, useState } from "react";
import Button from "@/refresh-components/buttons/Button";
import { useProjectsContext } from "@/app/chat/projects/ProjectsContext";
import InputTextarea from "@/refresh-components/inputs/InputTextArea";
import { useModal } from "@/refresh-components/contexts/ModalContext";
import { SvgAddLines } from "@opal/icons";
import Modal from "@/refresh-components/Modal";

export default function AddInstructionModal() {
  const modal = useModal();
  const { currentProjectDetails, upsertInstructions } = useProjectsContext();
  const [instructionText, setInstructionText] = useState("");

  useEffect(() => {
    if (!modal.isOpen) return;
    const preset = currentProjectDetails?.project?.instructions ?? "";
    setInstructionText(preset);
  }, [modal.isOpen, currentProjectDetails?.project?.instructions]);

  async function handleSubmit() {
    const value = instructionText.trim();
    try {
      await upsertInstructions(value);
    } catch (e) {
      console.error("Failed to save instructions", e);
    }
    modal.toggle(false);
  }

  return (
    <Modal open={modal.isOpen} onOpenChange={modal.toggle}>
      <Modal.Content mini>
        <Modal.Header
          icon={SvgAddLines}
          title="Set Project Instructions"
          description="Instruct specific behaviors, focus, tones, or formats for the response in this project."
          onClose={() => modal.toggle(false)}
        />
        <Modal.Body>
          <InputTextarea
            value={instructionText}
            onChange={(event) => setInstructionText(event.target.value)}
            placeholder="Think step by step and show reasoning for complex problems. Use specific examples."
          />
        </Modal.Body>
        <Modal.Footer>
          <Button secondary onClick={() => modal.toggle(false)}>
            Cancel
          </Button>
          <Button onClick={handleSubmit}>Save Instructions</Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
