"use client";

import { useCallback, type MouseEvent } from "react";
import { useTranslations } from "next-intl";
import { Button, Switch, Tag, Tooltip } from "@opal/components";
import { Content } from "@opal/layouts";
import { SvgBlocks, SvgEdit, SvgPlug, SvgUser } from "@opal/icons";
import { CardItemLayout } from "@/layouts/general-layouts";
import { Interactive } from "@opal/core";
import { Card } from "@/refresh-components/cards";
import { useSettings } from "@/lib/settings/hooks";
import type {
  CustomSkill,
  SkillExternalAppDependency,
} from "@/lib/skills/types";
import { cn } from "@opal/utils";

export type SkillCardSource = "builtin" | "custom";

interface SkillCardItemBase {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  can_toggle: boolean;
  /** External app this skill needs. Required for both sources: a built-in
   * provider's associated skill is a built-in row, so reading this off the
   * custom variant only would silently drop every built-in app. */
  external_app: SkillExternalAppDependency | null;
}

export interface BuiltinSkillCardItem extends SkillCardItemBase {
  source: "builtin";
  is_available: boolean;
  unavailable_reason?: string | null;
}

export interface CustomSkillCardItem extends SkillCardItemBase {
  source: "custom";
  skill: CustomSkill;
  author_email?: string | null;
  /** True when the skill is a personal skill owned by the current user. */
  is_personal?: boolean;
}

export type SkillCardItem = BuiltinSkillCardItem | CustomSkillCardItem;

export interface SkillCardProps {
  item: SkillCardItem;
  hasEnabledNameConflict?: boolean;
  onClick?: (item: SkillCardItem) => void;
  onEdit?: (item: CustomSkillCardItem) => void;
  onEnabledChange?: (item: SkillCardItem, enabled: boolean) => void;
  enablementPending?: boolean;
}

export default function SkillCard({
  item,
  hasEnabledNameConflict = false,
  onClick,
  onEdit,
  onEnabledChange,
  enablementPending = false,
}: SkillCardProps) {
  const t = useTranslations("cards");
  const { appName } = useSettings();

  const handleClick = useCallback(() => {
    onClick?.(item);
  }, [onClick, item]);

  const authorTitle =
    item.source === "builtin" ? appName : item.author_email || appName;
  const dependency = item.external_app;
  const isDependencyUnavailable = dependency !== null && !dependency.ready;
  const isSelectedDependencyUnavailable =
    item.enabled && isDependencyUnavailable;
  const isInactive = !item.enabled || isDependencyUnavailable;
  const isInvalid = item.source === "custom" && item.skill.is_valid === false;
  const isBuiltinUnavailable = item.source === "builtin" && !item.is_available;
  let dependencyStatus: string | null = null;
  if (dependency) {
    if (!dependency.ready) {
      dependencyStatus = dependency.enabled
        ? item.enabled
          ? t("skill.dependency.connectToUse", { app: dependency.name })
          : t("skill.dependency.connectToEnable", { app: dependency.name })
        : t("skill.dependency.appDisabled", { app: dependency.name });
    } else {
      dependencyStatus =
        !item.enabled && hasEnabledNameConflict
          ? t("skill.dependency.nameConflict")
          : t("skill.dependency.usesApp", { app: dependency.name });
    }
  }

  let tooltip: string | undefined;
  if (isInvalid) {
    tooltip = t("skill.tooltips.invalid");
  } else if (isBuiltinUnavailable) {
    tooltip = t("skill.tooltips.unavailable");
  } else if (isDependencyUnavailable && dependency) {
    tooltip = dependency.enabled
      ? t("skill.tooltips.connectApp", { app: dependency.name })
      : t("skill.tooltips.appDisabled", { app: dependency.name });
  }
  const canEdit =
    item.source === "custom" &&
    (item.skill.user_permission === "OWNER" ||
      item.skill.user_permission === "EDITOR");

  const handleEditClick = (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    if (item.source === "custom") {
      onEdit?.(item);
    }
  };

  const handleEnabledChange = (enabled: boolean) => {
    onEnabledChange?.(item, enabled);
  };

  const toggleAriaLabel = dependency
    ? item.enabled
      ? t("skill.toggle.disableForApp.ariaLabel", {
          name: item.name,
          app: dependency.name,
        })
      : t("skill.toggle.enableForApp.ariaLabel", {
          name: item.name,
          app: dependency.name,
        })
    : item.enabled
      ? t("skill.toggle.disable.ariaLabel", { name: item.name })
      : t("skill.toggle.enable.ariaLabel", { name: item.name });

  return (
    <Tooltip tooltip={tooltip} side="top">
      <Interactive.Simple onClick={handleClick} group="group/SkillCard">
        <Card
          variant={
            isInvalid ||
            isBuiltinUnavailable ||
            (isDependencyUnavailable && !item.enabled)
              ? "disabled"
              : isInactive
                ? "secondary"
                : "primary"
          }
          padding={0}
          gap={0}
          height="full"
        >
          <div
            className={cn(
              "flex self-stretch h-24",
              isSelectedDependencyUnavailable && "opacity-50"
            )}
          >
            <CardItemLayout
              icon={SvgBlocks}
              title={item.name}
              description={
                isInvalid ? t("skill.invalid.description") : item.description
              }
              rightChildren={
                item.source === "custom" && canEdit ? (
                  <div className="opacity-0 transition-opacity group-hover/SkillCard:opacity-100 group-focus-within/SkillCard:opacity-100">
                    <Button
                      prominence="secondary"
                      size="sm"
                      icon={SvgEdit}
                      tooltip={t("skill.edit.tooltip")}
                      onClick={handleEditClick}
                    />
                  </div>
                ) : undefined
              }
            />
          </div>

          <div className="bg-background-tint-01 p-1 flex flex-row items-center justify-between w-full">
            <div className="py-1 px-2 min-w-0 flex-1">
              <Content
                icon={dependency ? SvgPlug : SvgUser}
                title={dependencyStatus ?? authorTitle}
                sizePreset="secondary"
                variant="body"
                color="muted"
              />
            </div>
            <div className="p-0.5 pr-1.5 flex items-center gap-1">
              {item.can_toggle && (
                <div
                  role="presentation"
                  onClick={(event) => event.stopPropagation()}
                >
                  <Switch
                    checked={item.enabled}
                    onCheckedChange={handleEnabledChange}
                    disabled={enablementPending || isInvalid}
                    aria-label={toggleAriaLabel}
                  />
                </div>
              )}
              {item.source === "builtin" ? (
                item.is_available ? (
                  <Tag title={t("skill.tags.builtin.label")} color="blue" />
                ) : (
                  <Tag
                    title={t("skill.tags.unavailable.label")}
                    color="amber"
                  />
                )
              ) : isInvalid ? (
                <Tag title={t("skill.tags.invalid.label")} color="amber" />
              ) : dependency ? (
                <Tag title={t("skill.tags.appSkill.label")} color="blue" />
              ) : item.is_personal ? (
                <Tag title={t("skill.tags.personal.label")} color="purple" />
              ) : (
                <Tag title={t("skill.tags.custom.label")} color="gray" />
              )}
            </div>
          </div>
        </Card>
      </Interactive.Simple>
    </Tooltip>
  );
}
