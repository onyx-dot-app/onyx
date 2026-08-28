"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  Card,
  LineItemButton,
  Popover,
  PopoverMenu,
  Switch,
  Tag,
  Text,
} from "@opal/components";
import { Hoverable } from "@opal/core";
import { cn } from "@opal/utils";
// TODO(@raunakab): migrate to Opal LineItemButton once it supports danger variant
import { ConfirmationModalLayout, toast } from "@opal/layouts";
import { SvgEdit, SvgMoreHorizontal, SvgTrash } from "@opal/icons";
import { ConfiguredIntegration } from "@/views/admin/ExternalAppsPage/interfaces";

interface IntegrationCardProps {
  integration: ConfiguredIntegration;
}

export default function IntegrationCard({ integration }: IntegrationCardProps) {
  const {
    isCustom,
    logo: Logo,
    name,
    facts,
    warnings,
    enabled,
    toggleEnabled,
    edit,
    remove,
  } = integration;
  const t = useTranslations("admin.externalApps");
  const [isMutating, setIsMutating] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [confirmingRemoval, setConfirmingRemoval] = useState(false);

  async function run(
    action: () => Promise<void>,
    failureMessage: string
  ): Promise<boolean> {
    setIsMutating(true);
    try {
      await action();
      return true;
    } catch (e) {
      toast.error(e instanceof Error ? e.message : failureMessage);
      return false;
    } finally {
      setIsMutating(false);
    }
  }

  return (
    <Hoverable.Root group="integration-row">
      <Card background="light" border="solid" rounding={4}>
        <div className="flex items-center gap-3 w-full">
          {/* Off rows read as inert at a glance; controls keep full opacity. */}
          <div
            className={cn(
              "flex items-center gap-3 flex-1 min-w-0",
              !enabled && "opacity-60"
            )}
          >
            <Logo className="w-8 h-8 shrink-0" />
            <div className="flex-1 min-w-0 flex flex-col gap-0.5">
              <div className="flex items-center gap-2">
                <Text font="main-ui-action">{name}</Text>
                {isCustom && (
                  <Tag title={t("card.customTag.label")} color="purple" />
                )}
                {warnings.map((warning) => (
                  <Tag key={warning} title={warning} color="amber" error />
                ))}
              </div>
              <Text font="secondary-body" color="text-03">
                {facts.join(" · ")}
              </Text>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {/* Toggles org-wide availability, never a single member's
                connection; the label fades in on hover or focus. */}
            <Hoverable.Item group="integration-row" variant="appear-on-hover">
              <Text font="secondary-body" color="text-03" nowrap>
                {t("card.availableInCraft.label")}
              </Text>
            </Hoverable.Item>
            <Switch
              checked={enabled}
              onCheckedChange={() =>
                run(
                  toggleEnabled,
                  enabled
                    ? t("card.toasts.disableFailed", { name })
                    : t("card.toasts.enableFailed", { name })
                )
              }
              disabled={isMutating}
              aria-label={
                enabled
                  ? t("card.toggle.disableAriaLabel", { name })
                  : t("card.toggle.enableAriaLabel", { name })
              }
            />
            {/* Secondary actions live in an overflow menu at the card's edge.
                Every row renders the trigger, so the switch position is
                uniform whether or not a row can be edited or deleted. */}
            <Popover open={menuOpen} onOpenChange={setMenuOpen}>
              <Popover.Trigger asChild>
                <Button
                  prominence="tertiary"
                  icon={SvgMoreHorizontal}
                  disabled={isMutating || (!edit && !remove)}
                  aria-label={t("card.actionsButton.ariaLabel", { name })}
                />
              </Popover.Trigger>
              <Popover.Content align="end" width="sm">
                <PopoverMenu>
                  {[
                    edit ? (
                      <LineItemButton
                        sizePreset="main-ui"
                        rounding={2}
                        key="edit"
                        icon={SvgEdit}
                        onClick={() => {
                          setMenuOpen(false);
                          edit();
                        }}
                        title={t("card.editAction.label")}
                      />
                    ) : undefined,
                    remove ? (
                      <LineItemButton
                        sizePreset="main-ui"
                        rounding={2}
                        key="delete"
                        icon={SvgTrash}
                        color="danger"
                        onClick={() => {
                          setMenuOpen(false);
                          setConfirmingRemoval(true);
                        }}
                        title={t("card.deleteAction.label")}
                      />
                    ) : undefined,
                  ]}
                </PopoverMenu>
              </Popover.Content>
            </Popover>
          </div>
        </div>
        {confirmingRemoval && remove && (
          <ConfirmationModalLayout
            icon={SvgTrash}
            title={t("card.deleteModal.title", { name })}
            description={t("card.deleteModal.description")}
            onClose={isMutating ? undefined : () => setConfirmingRemoval(false)}
            submit={
              <Button
                variant="danger"
                disabled={isMutating}
                onClick={async () => {
                  const failure = t("card.toasts.deleteFailed", { name });
                  if (await run(remove.run, failure)) {
                    setConfirmingRemoval(false);
                  }
                }}
              >
                {isMutating
                  ? t("card.deleteModal.submitting.label")
                  : t("card.deleteModal.submit.label")}
              </Button>
            }
          >
            {t("card.deleteModal.retainedSkills", {
              count: remove.retainedCustomSkillCount,
            })}
          </ConfirmationModalLayout>
        )}
      </Card>
    </Hoverable.Root>
  );
}
