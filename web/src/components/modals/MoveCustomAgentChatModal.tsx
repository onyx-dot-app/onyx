"use client";

import { useState } from "react";
import ConfirmationModal from "@/refresh-components/modals/ConfirmationModal";
import { InfoIcon } from "@/components/icons/icons";
import Button from "@/refresh-components/buttons/Button";
import { Checkbox } from "@/components/ui/checkbox";
import Text from "@/refresh-components/Text";

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
    <ConfirmationModal
      icon={InfoIcon}
      title="Move Custom Agent Chat"
      description={
        <Text text03>
          This chat uses a <b>custom agent</b> and moving it to a <b>project</b>{" "}
          will not override the agent&apos;s prompt or knowledge configurations.
          This should only be used for organization purposes.
        </Text>
      }
      onClose={onCancel}
    >
      <div className="flex flex-col gap-spacing-paragraph">
        <div className="flex items-center justify-between gap-spacing-inline">
          <div className="flex items-center gap-spacing-inline">
            <Checkbox
              id="move-custom-agent-do-not-show"
              checked={doNotShowAgain}
              onCheckedChange={(checked) => setDoNotShowAgain(Boolean(checked))}
            />
            <label
              htmlFor="move-custom-agent-do-not-show"
              className="text-text-03 text-sm"
            >
              Do not show this again
            </label>
          </div>
          <div className="flex justify-end gap-spacing-inline">
            <Button secondary onClick={onCancel}>
              Cancel
            </Button>
            <Button primary onClick={() => onConfirm(doNotShowAgain)}>
              Confirm Move
            </Button>
          </div>
        </div>
      </div>
    </ConfirmationModal>
  );
}
