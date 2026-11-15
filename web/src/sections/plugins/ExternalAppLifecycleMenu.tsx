"use client";

import { useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useSWRConfig } from "swr";
import { Button, useCreateModal } from "@opal/components";
import { SvgTrash } from "@opal/icons";
import { toast, ConfirmationModalLayout } from "@opal/layouts";
import type { ExternalAppAdminResponse } from "@/app/craft/v1/apps/registry";
import { deleteExternalApp } from "@/app/craft/services/externalAppsService";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { PluginLifecycleMenuProps } from "@/sections/plugins/PluginLifecycleMenu";

export default function ExternalAppLifecycleMenu({
  app,
  renderStatus,
}: {
  app: ExternalAppAdminResponse;
  renderStatus?: PluginLifecycleMenuProps["renderStatus"];
}) {
  const t = useTranslations("admin.externalApps");
  const { mutate } = useSWRConfig();
  const confirmModal = useCreateModal();
  const [pending, setPending] = useState(false);
  const writing = useRef(false);
  async function removeApp() {
    if (writing.current) return;
    writing.current = true;
    setPending(true);
    try {
      await deleteExternalApp(app.id);
      confirmModal.toggle(false);
      await mutate(SWR_KEYS.buildExternalAppsAdmin);
    } catch (cause) {
      toast.error(
        cause instanceof Error
          ? cause.message
          : t("card.toasts.enableFailed", { name: app.name })
      );
    } finally {
      writing.current = false;
      setPending(false);
    }
  }
  return (
    <>
      <div className="flex items-center gap-2">
        {renderStatus?.({
          disabled: pending,
        })}
        {!app.is_onyx_managed ? (
          <Button
            icon={SvgTrash}
            size="sm"
            prominence="tertiary"
            disabled={pending}
            aria-label={t("card.deleteAction.label")}
            tooltip={t("card.deleteAction.label")}
            onClick={() => {
              confirmModal.toggle(true);
            }}
          />
        ) : (
          <span className="size-6 shrink-0" />
        )}
      </div>
      <confirmModal.Provider>
        <ConfirmationModalLayout
          icon={SvgTrash}
          title={t("card.deleteModal.title", { name: app.name })}
          description={t("card.deleteModal.description")}
          onClose={pending ? undefined : () => confirmModal.toggle(false)}
          submit={
            <Button
              variant="danger"
              disabled={pending}
              onClick={() => void removeApp()}
            >
              {t("card.deleteModal.submit.label")}
            </Button>
          }
        >
          {t("card.deleteModal.retainedSkills", {
            count: app.associated_skills.length,
          })}
        </ConfirmationModalLayout>
      </confirmModal.Provider>
    </>
  );
}
