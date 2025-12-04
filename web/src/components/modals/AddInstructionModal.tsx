"use client";

import { useEffect, useState } from "react";
import Button from "@/refresh-components/buttons/Button";
import DefaultModalLayout from "@/refresh-components/layouts/DefaultModalLayout";
import { useProjectsContext } from "@/app/chat/projects/ProjectsContext";
import SvgAddLines from "@/icons/add-lines";
import InputTextarea from "@/refresh-components/inputs/InputTextArea";
import { useModal } from "@/refresh-components/contexts/ModalContext";

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
    <DefaultModalLayout
      icon={SvgAddLines}
      title="Set Project Instructions"
      description="Instruct specific behaviors, focus, tones, or formats for the response in this project."
      mini
    >
      <div className="bg-background-tint-01 p-4">
        <InputTextarea
          value={instructionText}
          onChange={(event) => setInstructionText(event.target.value)}
          placeholder="Think step by step and show reasoning for complex problems. Use specific examples."
        />
      </div>
      <div className="flex flex-row justify-end gap-2 p-4">
        <Button secondary onClick={() => modal.toggle(false)}>
          Cancel
        </Button>
        <Button onClick={handleSubmit}>Save Instructions</Button>
      </div>
    </DefaultModalLayout>
  );
}
