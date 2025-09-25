"use client";

import { Modal } from "../Modal";
import { Button } from "../ui/button";
import { Checkbox } from "../ui/checkbox";
import { InfoIcon } from "../icons/icons";
import { useState } from "react";

interface MoveCustomAgentChatModalProps {
  isOpen: boolean;
  onCancel: () => void;
  onConfirm: (doNotShowAgain: boolean) => void;
}

export default function MoveCustomAgentChatModal({
  isOpen,
  onCancel,
  onConfirm,
}: MoveCustomAgentChatModalProps) {
  const [doNotShowAgain, setDoNotShowAgain] = useState(false);

  if (!isOpen) return null;

  return (
    <Modal onOutsideClick={onCancel} width="rounded-xl max-w-lg w-full">
      <div className="space-y-5 text-onyx-medium">
        <div className="flex flex-col gap-2">
          <InfoIcon size={24} />
          <h2 className="text-2xl font-bold">Move Custom Agent Chat</h2>
        </div>

        <p className="text-base">
          This chat uses a <b>custom agent</b> and moving it to a <b>project</b>{" "}
          will not override the agent&apos;s prompt or knowledge configurations.
          This should only be used for organization purposes.
        </p>
        <div className="flex items-center justify-between gap-2 pt-2">
          <div className="flex items-center gap-2">
            <Checkbox
              id="move-custom-agent-do-not-show"
              checked={doNotShowAgain}
              onCheckedChange={(checked) => setDoNotShowAgain(Boolean(checked))}
            />
            <label htmlFor="move-custom-agent-do-not-show" className="text-sm">
              Do not show this again
            </label>
          </div>
          <div className="flex gap-2">
            <Button onClick={onCancel} variant="outline">
              Cancel
            </Button>
            <Button onClick={() => onConfirm(doNotShowAgain)}>
              Confirm Move
            </Button>
          </div>
        </div>
      </div>
    </Modal>
  );
}
