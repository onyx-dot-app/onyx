"use client";

import { useTranslations } from "next-intl";
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
  const t = useTranslations("skills.modals");

  return (
    <ConfirmationModalLayout
      icon={SvgAlertTriangle}
      title={t("nameConflict.title", { name: skillName })}
      description={t("nameConflict.description")}
      onClose={pending ? undefined : onClose}
      submit={
        <Button onClick={onConfirm} disabled={pending}>
          {pending
            ? t("nameConflict.confirmButton.pendingLabel")
            : t("nameConflict.confirmButton.label")}
        </Button>
      }
    >
      {t("nameConflict.body")}
    </ConfirmationModalLayout>
  );
}
