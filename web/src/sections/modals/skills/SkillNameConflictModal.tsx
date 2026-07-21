"use client";

import { Button } from "@opal/components";
import { SvgAlertTriangle } from "@opal/icons";
import { ConfirmationModalLayout } from "@opal/layouts";

interface SkillNameConflictModalProps {
  skillName: string;
  onClose: () => void;
  onConfirm: () => void;
  pending?: boolean;
}

export default function SkillNameConflictModal({
  skillName,
  onClose,
  onConfirm,
  pending = false,
}: SkillNameConflictModalProps) {
  return (
    <ConfirmationModalLayout
      icon={SvgAlertTriangle}
      title={`Create another “${skillName}” skill?`}
      description="You already have an enabled skill with this name."
      onClose={pending ? undefined : onClose}
      submit={
        <Button onClick={onConfirm} disabled={pending}>
          {pending ? "Creating..." : "Create anyway"}
        </Button>
      }
    >
      The new skill will start disabled. You can switch which one is active from
      the Skills page.
    </ConfirmationModalLayout>
  );
}
