"use client";

import { useState } from "react";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import { Button } from "@opal/components";
import { Checkbox } from "@opal/components";
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
      title="移动自定义智能体聊天"
      onClose={onCancel}
      submit={
        <Button onClick={() => onConfirm(doNotShowAgain)}>确认移动</Button>
      }
    >
      <div className="flex flex-col gap-4">
        <Text as="p" text03>
          此聊天使用了<b>自定义智能体</b>。将它移动到<b>项目</b>不会覆盖该智能体的提示词或知识配置，
          仅用于整理归类。
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
            不再显示
          </label>
        </div>
      </div>
    </ConfirmationModalLayout>
  );
}
