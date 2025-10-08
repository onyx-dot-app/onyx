"use client";

import { useEffect, useState } from "react";
import Button from "@/refresh-components/buttons/Button";
import CoreModal from "@/refresh-components/modals/CoreModal";
import {
  ModalIds,
  useChatModal,
} from "@/refresh-components/contexts/ChatModalContext";
import { useProjectsContext } from "@/app/chat/projects/ProjectsContext";
import { useEscape, useKeyPress } from "@/hooks/useKeyPress";
import Text from "@/refresh-components/Text";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgX from "@/icons/x";
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

  useKeyPress(handleSubmit, "Enter", open);
  useEscape(onClose, open);

  if (!open) return null;

  return (
    <CoreModal
      className="w-[32rem] rounded-16 border flex flex-col bg-background-tint-00"
      onClickOutside={() => onClose()}
    >
      <div className="flex flex-col items-center justify-center gap-spacing-inline p-spacing-paragraph">
        <div className="h-[1.5rem] flex flex-row justify-between items-center w-full">
          <SvgAddLines className="w-[1.5rem] h-[1.5rem] stroke-text-04" />
          <IconButton icon={SvgX} internal onClick={onClose} />
        </div>
        <Text headingH3 text04 className="w-full text-left">
          Set Project Instructions
        </Text>
        <Text text03>
          Instruct specific behaviors, focus, tones, or formats for the response
          in this project.
        </Text>
      </div>
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
    </CoreModal>
  );
}
