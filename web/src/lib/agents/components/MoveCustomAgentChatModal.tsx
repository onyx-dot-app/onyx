"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { ConfirmationModalLayout } from "@opal/layouts";
import { Button } from "@opal/components";
import { Checkbox } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import { SvgAlertCircle } from "@opal/icons";
interface MoveCustomAgentChatModalProps {
  onCancel: () => void;
  onConfirm: (doNotShowAgain: boolean) => void;
}

export function MoveCustomAgentChatModal({
  onCancel,
  onConfirm,
}: MoveCustomAgentChatModalProps) {
  const t = useTranslations("agents.modals");
  const [doNotShowAgain, setDoNotShowAgain] = useState(false);

  return (
    <ConfirmationModalLayout
      icon={SvgAlertCircle}
      title={t("moveCustomAgentChat.title")}
      onClose={onCancel}
      submit={
        <Button onClick={() => onConfirm(doNotShowAgain)}>
          {t("moveCustomAgentChat.confirm.label")}
        </Button>
      }
    >
      <div className="flex flex-col gap-4">
        <Text as="p" text03>
          {t.rich("moveCustomAgentChat.body.description", {
            b: (chunks) => <b>{chunks}</b>,
          })}
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
            {t("moveCustomAgentChat.doNotShowAgain.label")}
          </label>
        </div>
      </div>
    </ConfirmationModalLayout>
  );
}
