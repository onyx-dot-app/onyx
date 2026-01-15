"use client";

import { useState } from "react";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import Button from "@/refresh-components/buttons/Button";
import Checkbox from "@/refresh-components/inputs/Checkbox";
import Text from "@/refresh-components/texts/Text";
import { SvgAlertCircle } from "@opal/icons";
interface MoveCustomAgentChatModalProps {
  onCancel: () => void;
  onConfirm: (doNotShowAgain: boolean) => void;
}

export default function MoveCustomAgentChatModal({
  onCancel,
  onConfirm,
}: MoveCustomAgentChatModalProps) {
  const [doNotShowAgain, setDoNotShowAgain] = useState(false);

  return (
    <ConfirmationModalLayout
      icon={SvgAlertCircle}
      title="Move Custom Agent Chat"
      onClose={onCancel}
      submit={
        <Button primary onClick={() => onConfirm(doNotShowAgain)}>
          Confirm Move
        </Button>
      }
    >
      <div className="flex flex-col gap-4">
        <Text as="p" text03>
          This chat uses a <b>custom agent</b> and moving it to a <b>project</b>{" "}
          will not override the agent&apos;s prompt or knowledge configurations.
          This should only be used for organization purposes.
        </Text>
        <div className="flex items-center gap-1">
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
      </div>
    </ConfirmationModalLayout>
  );
}
