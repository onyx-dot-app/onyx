"use client";

import { useTranslations } from "next-intl";
import { LinkButton, useCreateModal } from "@opal/components";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { useSettings } from "@/lib/settings/hooks";
import { ApplicationStatus } from "@/lib/settings/types";
import DowngradeToCommunityModal from "@/sections/modals/DowngradeToCommunityModal";

// Renders only once a self-hosted deployment is locked out. During the grace
// period a renewal can still arrive, so the offer waits.
export default function DowngradeToCommunityLink() {
  const t = useTranslations("admin.billing.downgrade");
  const settings = useSettings();
  const modal = useCreateModal();

  const canDowngrade: boolean =
    !NEXT_PUBLIC_CLOUD_ENABLED &&
    settings.application_status === ApplicationStatus.GATED_ACCESS;
  if (!canDowngrade) return null;

  return (
    <>
      <LinkButton onClick={() => modal.toggle(true)} external={false}>
        {t("link.label")}
      </LinkButton>
      {modal.isOpen && (
        <DowngradeToCommunityModal onClose={() => modal.toggle(false)} />
      )}
    </>
  );
}
