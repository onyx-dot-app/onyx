"use client";

import { cn, markdown } from "@opal/utils";
import { useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useSWRConfig } from "swr";
import { Button, Dropdown, type DropdownMenuItem } from "@opal/components";
import { SvgSettings, SvgTrash, SvgUnplug } from "@opal/icons";
import { toast, ConfirmationModalLayout } from "@opal/layouts";
import type { ExternalAppAdminResponse } from "@/app/craft/v1/apps/registry";
import {
  deleteExternalApp,
  updateExternalApp,
} from "@/app/craft/services/externalAppsService";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  DeleteReveal,
  type PluginLifecycleMenuProps,
} from "@/sections/plugins/PluginLifecycleMenu";
import { workspaceAvailabilityLabel } from "@/sections/plugins/workspaceAvailability";

export default function ExternalAppLifecycleMenu({
  app,
  renderStatus,
  deleteHoverGroup,
  size = "sm",
}: {
  app: ExternalAppAdminResponse;
  renderStatus?: PluginLifecycleMenuProps["renderStatus"];
  deleteHoverGroup?: PluginLifecycleMenuProps["deleteHoverGroup"];
  size?: PluginLifecycleMenuProps["size"];
}) {
  const t = useTranslations("admin.externalApps");
  const tp = useTranslations("actions.plugins");
  const availabilityLabel = tp(
    `controls.${workspaceAvailabilityLabel({ kind: "external-app", app }, false)}`
  );
  const { mutate } = useSWRConfig();
  const [confirm, setConfirm] = useState(false);
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const writing = useRef(false);
  async function write(remove: boolean) {
    if (writing.current) return;
    writing.current = true;
    setPending(true);
    try {
      if (remove) await deleteExternalApp(app.id);
      else await updateExternalApp(app.id, { enabled: !app.enabled });
      setConfirm(false);
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
  const items: DropdownMenuItem[] = [
    {
      kind: "action",
      id: "availability",
      icon: SvgUnplug,
      title: tp(app.enabled ? "controls.disableCraft" : "controls.enableCraft"),
      disabled: pending,
      onSelect: () => void write(false),
    },
  ];
  return (
    <>
      <div
        className={cn("flex items-center", size === "md" ? "gap-1" : "gap-2")}
      >
        {renderStatus?.({
          onOpen: () => setOpen(true),
          disabled: pending,
          expanded: open,
        })}
        {!app.is_onyx_managed ? (
          <DeleteReveal group={deleteHoverGroup}>
            <Button
              icon={SvgTrash}
              size={size}
              prominence="tertiary"
              disabled={pending}
              aria-label={t("card.deleteAction.label")}
              tooltip={t("card.deleteAction.label")}
              onClick={() => {
                setOpen(false);
                setConfirm(true);
              }}
            />
          </DeleteReveal>
        ) : (
          <span
            className={cn("shrink-0", size === "md" ? "size-8" : "size-6")}
          />
        )}
        <Dropdown open={open} onOpenChange={setOpen} align="end">
          <Dropdown.Trigger asChild>
            <Button
              icon={SvgSettings}
              size={size}
              prominence="tertiary"
              disabled={pending}
              aria-label={availabilityLabel}
              tooltip={availabilityLabel}
            />
          </Dropdown.Trigger>
          <Dropdown.Data label={availabilityLabel} items={items} />
        </Dropdown>
      </div>
      {confirm && (
        <ConfirmationModalLayout
          icon={SvgTrash}
          title={markdown(tp("deleteModal.title", { name: app.name }))}
          description={t("card.deleteModal.description")}
          onClose={pending ? undefined : () => setConfirm(false)}
          submit={
            <Button
              variant="danger"
              disabled={pending}
              onClick={() => void write(true)}
            >
              {t("card.deleteModal.submit.label")}
            </Button>
          }
        >
          {t("card.deleteModal.retainedSkills", {
            count: app.associated_skills.length,
          })}
        </ConfirmationModalLayout>
      )}
    </>
  );
}
