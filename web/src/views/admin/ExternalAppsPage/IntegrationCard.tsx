"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  Dropdown,
  Card,
  type DropdownMenuItem,
  InputSwitch,
  Tag,
  Text,
} from "@opal/components";
import { Hoverable } from "@opal/core";
import { cn } from "@opal/utils";
import { ConfirmationModalLayout, toast } from "@opal/layouts";
import { SvgMoreHorizontal, SvgTrash } from "@opal/icons";
import { ConfiguredIntegration } from "@/views/admin/ExternalAppsPage/types";

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
    menuActions,
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

  const menuItems: DropdownMenuItem[] = [
    ...menuActions.map((action) => ({ kind: "action" as const, ...action })),
    ...(remove
      ? [
          {
            kind: "action" as const,
            id: "delete",
            icon: SvgTrash,
            danger: true,
            title: t("card.deleteAction.label"),
            onSelect: () => setConfirmingRemoval(true),
          },
        ]
      : []),
  ];

  return (
    <Hoverable.Root group="integration-card" width="full">
      <Card color="background-tint-00" border="solid" rounding={4}>
        <div className="flex flex-col gap-3 w-full">
          <div className="flex items-center justify-between gap-3">
            <div
              className={cn(
                "flex items-center gap-3 min-w-0 flex-1",
                !enabled && "opacity-60"
              )}
            >
              <Logo className="w-8 h-8 shrink-0" />
              <div className="min-w-0 flex-1">
                <Text font="main-ui-action" maxLines={2} title={name}>
                  {name}
                </Text>
              </div>
            </div>
            <Dropdown
              open={menuOpen}
              onOpenChange={setMenuOpen}
              width={60}
              align="start"
            >
              <Dropdown.Trigger asChild>
                <Button
                  prominence="tertiary"
                  icon={SvgMoreHorizontal}
                  disabled={isMutating || (menuActions.length === 0 && !remove)}
                  aria-label={t("card.actionsButton.ariaLabel", { name })}
                />
              </Dropdown.Trigger>
              <Dropdown.Data
                label={t("card.actionsButton.ariaLabel", { name })}
                items={menuItems}
              />
            </Dropdown>
          </div>
          <div className="flex items-center justify-between gap-3">
            <div
              className={cn(
                "flex flex-wrap items-center gap-x-2 gap-y-1 min-w-0",
                !enabled && "opacity-60"
              )}
            >
              {isCustom && (
                <Tag title={t("card.customTag.label")} color="purple" />
              )}
              <Text font="secondary-body" color="text-03">
                {facts.join(" · ")}
              </Text>
            </div>
            <div className="flex shrink-0 items-center justify-end gap-2">
              <Hoverable.Item
                group="integration-card"
                variant="appear-on-hover"
              >
                <Text font="secondary-body" color="text-03">
                  {t("card.availableInCraft.label")}
                </Text>
              </Hoverable.Item>
              <InputSwitch
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
            </div>
          </div>
          {warnings.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {warnings.map((warning) => (
                <Tag key={warning} title={warning} color="amber" error />
              ))}
            </div>
          )}
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
