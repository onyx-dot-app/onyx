"use client";

import { useTranslations } from "next-intl";
import { Button } from "@opal/components";
import { ConfirmationModalLayout } from "@opal/layouts";
import { SvgAlertTriangle } from "@opal/icons";
import type { SkillEnablement } from "@/lib/skills/hooks";

interface SkillSwitchModalProps {
  enablement: SkillEnablement;
}

/** Confirms turning on a skill or plugin whose skill name another enabled
 * one holds, and names the ones it turns off. */
export default function SkillSwitchModal({
  enablement,
}: SkillSwitchModalProps) {
  const t = useTranslations("skills");
  const { switchTarget: target, switchConflicts, switchModal } = enablement;
  const pending = target !== null && enablement.isPending(target.id);
  const names = switchConflicts.map((name) => `“${name}”`).join(", ");
  return (
    <switchModal.Provider>
      {target && (
        <ConfirmationModalLayout
          icon={SvgAlertTriangle}
          title={t("page.switchModal.title", { name: target.name })}
          description={
            names
              ? t("page.switchModal.descriptionNamed", {
                  name: target.name,
                  names,
                })
              : t("page.switchModal.description", { name: target.name })
          }
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
          {names
            ? t("page.switchModal.bodyNamed", { name: target.name, names })
            : t("page.switchModal.body")}
        </ConfirmationModalLayout>
      )}
    </switchModal.Provider>
  );
}
