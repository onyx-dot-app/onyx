import i18n from "@/i18n/init";
import k from "./../../../i18n/keys";
import React from "react";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";

interface MakePublicAssistantPopoverProps {
  isPublic: boolean;
  onShare: (shared: boolean) => void;
  onClose: () => void;
}

export function MakePublicAssistantPopover({
  isPublic,
  onShare,
  onClose,
}: MakePublicAssistantPopoverProps) {
  return (
    <div className="p-4 space-y-4">
      <h2 className="text-lg font-semibold">
        {isPublic
          ? i18n.t(k.PUBLIC_ASSISTANT)
          : i18n.t(k.MAKE_ASSISTANT_PUBLIC)}
      </h2>

      <p className="text-sm">
        {i18n.t(k.THIS_ASSISTANT_IS_CURRENTLY)}{" "}
        <span className="font-semibold">
          {isPublic ? i18n.t(k.PUBLIC1) : i18n.t(k.PRIVATE)}
        </span>
        {i18n.t(k._8)}
        {isPublic
          ? i18n.t(k.ANYONE_CAN_CURRENTLY_ACCESS_TH)
          : i18n.t(k.ONLY_YOU_CAN_ACCESS_THIS_ASSIS)}
      </p>

      <Separator />

      {isPublic ? (
        <div className="space-y-4">
          <p className="text-sm">{i18n.t(k.TO_RESTRICT_ACCESS_TO_THIS_ASS)}</p>
          <Button
            onClick={async () => {
              await onShare(false);
              onClose();
            }}
            size="sm"
            variant="destructive"
          >
            {i18n.t(k.MAKE_ASSISTANT_PRIVATE)}
          </Button>
        </div>
      ) : (
        <div className="space-y-4">
          <p className="text-sm">{i18n.t(k.MAKING_THIS_ASSISTANT_PUBLIC_W)}</p>
          <Button
            onClick={async () => {
              await onShare(true);
              onClose();
            }}
            size="sm"
          >
            {i18n.t(k.MAKE_ASSISTANT_PUBLIC)}
          </Button>
        </div>
      )}
    </div>
  );
}
