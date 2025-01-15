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
        {isPublic ? "Public Assistant" : "Make Assistant Public"}
      </h2>

      <p className="text-sm">
        This assistant is currently{" "}
        <span className="font-semibold">{isPublic ? "public" : "private"}</span>
        .
        {isPublic
          ? " Anyone can currently access this assistant."
          : " Only you can access this assistant."}
      </p>

      <Separator />

      {isPublic ? (
        <div className="space-y-4">
          <p className="text-sm">
            To restrict access to this assistant, you can make it private again.
          </p>
          <Button
            onClick={async () => {
              await onShare(false);
              onClose();
            }}
            size="sm"
            variant="destructive"
          >
            Make Assistant Private
          </Button>
        </div>
      ) : (
        <div className="space-y-4">
          <p className="text-sm">
            Making this assistant public will allow anyone with the link to view
            and use it. Ensure that all content and capabilities of the
            assistant are safe to share.
          </p>
          <Button
            onClick={async () => {
              await onShare(true);
              onClose();
            }}
            size="sm"
          >
            Make Assistant Public
          </Button>
        </div>
      )}
    </div>
  );
}
