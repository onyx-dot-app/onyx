"use client";

import { useTranslations } from "next-intl";
import { Button } from "@opal/components";
import { ConfirmationModalLayout } from "@opal/layouts";
import { SvgAlertTriangle } from "@opal/icons";
import type { SkillEnablement } from "@/lib/skills/hooks";

interface SkillSwitchModalProps {
  enablement: SkillEnablement;
}

/** Confirms turning on a skill whose name another enabled skill holds. */
export default function SkillSwitchModal({
  enablement,
}: SkillSwitchModalProps) {
  const t = useTranslations("skills");
  const { switchTarget: target, switchModal } = enablement;
  const pending = target !== null && enablement.isPending(target.id);
  return (
    <switchModal.Provider>
      {target && (
        <ConfirmationModalLayout
          icon={SvgAlertTriangle}
          title={t("page.switchModal.title", { name: target.name })}
          description={t("page.switchModal.description", {
            name: target.name,
          })}
          onClose={pending ? undefined : () => switchModal.toggle(false)}
          submit={
            <Button
              disabled={pending}
              onClick={() => void enablement.setEnabled(target, true, true)}
            >
              {pending
                ? t("page.switchModal.submit.pendingLabel")
                : t("page.switchModal.submit.label")}
            </Button>
          }
        >
          {t("page.switchModal.body")}
        </ConfirmationModalLayout>
      )}
    </switchModal.Provider>
  );
}
