"use client";

import { useCallback, type MouseEvent } from "react";
import { useFormatter, useTranslations } from "next-intl";
import {
  Button,
  Card,
  InputSwitch,
  InputCheckbox,
  Badge,
  Text,
  Tooltip,
} from "@opal/components";
import { Content, Section } from "@opal/layouts";
import {
  SvgBlocks,
  SvgEdit,
  SvgPlug,
  SvgShare,
  SvgTrash,
  SvgUser,
} from "@opal/icons";
import { useUser } from "@/providers/UserProvider";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { Permission } from "@/lib/types";
import { useSettings } from "@/lib/settings/hooks";
import type {
  CustomSkill,
  SkillExternalAppDependency,
} from "@/lib/skills/types";
import { cn } from "@opal/utils";
import { hasUnpublishedChanges } from "@/lib/skills/sharing";
import { useInstallationPolicyCopy } from "@/lib/skills/installationPolicy";

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
  onShare?: (item: CustomSkillCardItem) => void;
  onDelete?: (item: CustomSkillCardItem) => void;
  onEnabledChange?: (item: SkillCardItem, enabled: boolean) => void;
  enablementPending?: boolean;
  selection?: {
    checked: boolean;
    disabled: boolean;
    onCheckedChange: (checked: boolean) => void;
  };
}

export default function SkillCard({
  item,
  hasEnabledNameConflict = false,
  onClick,
  onEdit,
  onShare,
  onDelete,
  onEnabledChange,
  enablementPending = false,
  selection,
}: SkillCardProps) {
  const t = useTranslations("cards");
  const skillCopy = useTranslations("skills");
  const { appName } = useSettings();
  const format = useFormatter();
  const policyCopy = useInstallationPolicyCopy();

  const handleClick = useCallback(() => {
    onClick?.(item);
  }, [onClick, item]);

  const { isAdmin } = useUser();
  const { isGlobalHolder: canManageOrgSkills } = usePermissionAuthority(
    Permission.MANAGE_PLUGINS
  );
  const isRequired =
    item.source === "custom" && item.skill.installation_policy === "REQUIRED";
  // Only an organization-wide skill manager can delete a published skill.
  const canDelete =
    item.source === "custom" &&
    (!isRequired || isAdmin) &&
    (item.skill.public_permission === null || canManageOrgSkills);

  // Only callers who may see share details get summaries.
  const groupSummaries =
    item.source === "custom" ? item.skill.group_summaries : [];
  const groupsLine =
    groupSummaries.length > 0
      ? skillCopy("groups.card", {
          groups: format.list(
            groupSummaries.map((summary) =>
              summary.installation_policy === null
                ? summary.group_name
                : skillCopy("groups.entry", {
                    name: summary.group_name,
                    policy: policyCopy.label(summary.installation_policy),
                  })
            )
          ),
        })
      : null;

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
      <Card
        data-testid="SkillCard"
        onClick={handleClick}
        className="group/SkillCard cursor-pointer"
        disabled={
          isInvalid ||
          isBuiltinUnavailable ||
          (isDependencyUnavailable && !item.enabled)
        }
        color={isInactive ? "transparent" : "background-tint-00"}
        border="solid"
        rounding={4}
        padding={0}
        height="full"
      >
        <Section
          height={6}
          gap={1}
          padding={1}
          alignItems="stretch"
          justifyContent="start"
          className={cn(isSelectedDependencyUnavailable && "opacity-50")}
        >
          <Section
            flexDirection="row"
            justifyContent="between"
            height="auto"
            gap={1}
          >
            <Section
              flexDirection="row"
              height="auto"
              justifyContent="start"
              gap={0}
              width="auto"
            >
              {selection && (
                <Section
                  width="auto"
                  height="auto"
                  padding={2}
                  onClick={(event) => event.stopPropagation()}
                >
                  <InputCheckbox
                    checked={selection.checked}
                    disabled={selection.disabled}
                    onCheckedChange={selection.onCheckedChange}
                    aria-label={skillCopy("bulk.selectSkill", {
                      name: item.name,
                    })}
                  />
                </Section>
              )}
              <Button
                prominence="internal"
                icon={selection ? undefined : SvgBlocks}
                aria-label={item.name}
                onClick={(event) => {
                  event.stopPropagation();
                  handleClick();
                }}
              >
                {item.name}
              </Button>
            </Section>
            {item.source === "custom" && canEdit && !selection?.checked ? (
              <Section
                flexDirection="row"
                justifyContent="start"
                width="fit"
                height="auto"
                gap={1}
                className="opacity-0 transition-opacity group-hover/SkillCard:opacity-100 group-focus-within/SkillCard:opacity-100 no-hover:opacity-100"
              >
                {onShare && (
                  <Button
                    prominence="secondary"
                    size="sm"
                    icon={SvgShare}
                    tooltip={skillCopy("editor.management.sharing.edit.label")}
                    aria-label={skillCopy(
                      "editor.management.sharing.edit.label"
                    )}
                    onClick={(event) => {
                      event.stopPropagation();
                      onShare(item);
                    }}
                  />
                )}
                <Button
                  prominence="secondary"
                  size="sm"
                  icon={SvgEdit}
                  tooltip={t("skill.edit.tooltip")}
                  aria-label={t("skill.edit.tooltip")}
                  onClick={handleEditClick}
                />
                {onDelete && canDelete && (
                  <Button
                    prominence="secondary"
                    variant="danger"
                    size="sm"
                    icon={SvgTrash}
                    tooltip={skillCopy("editor.delete.button.label")}
                    aria-label={skillCopy("editor.delete.button.label")}
                    onClick={(event) => {
                      event.stopPropagation();
                      onDelete(item);
                    }}
                  />
                )}
              </Section>
            ) : undefined}
          </Section>
          <Section padding={2} gap={0} height="auto" alignItems="stretch">
            <Text
              font="secondary-body"
              color="text-03"
              maxLines={2}
              wordWrap="wrap-break-word"
            >
              {isInvalid ? t("skill.invalid.description") : item.description}
            </Text>
          </Section>
        </Section>

        {groupsLine && (
          <Section height="auto" alignItems="stretch" padding={2}>
            <Text
              font="secondary-body"
              color="text-03"
              maxLines={1}
              overflowTooltip
            >
              {groupsLine}
            </Text>
          </Section>
        )}
        <Section
          flexDirection="row"
          height="auto"
          justifyContent="between"
          padding={1}
          gap={0}
          className="bg-background-tint-01"
        >
          <Section
            height="auto"
            width="auto"
            padding={1}
            className="min-w-0 flex-1"
          >
            <Content
              font="secondary-body"
              icon={dependency ? SvgPlug : SvgUser}
              title={dependencyStatus ?? authorTitle}
              titleColor="text-03"
            />
          </Section>
          <Section
            flexDirection="row"
            height="auto"
            width="auto"
            padding={0.5}
            gap={1}
            className="me-1"
          >
            {isRequired && (
              <Badge
                title={skillCopy("installationPolicy.REQUIRED.label")}
                color="info"
                tooltip={t("skill.tags.required.tooltip")}
              />
            )}
            {item.can_toggle && (
              <Section
                width="auto"
                height="auto"
                role="presentation"
                onClick={(event) => event.stopPropagation()}
              >
                <InputSwitch
                  checked={item.enabled}
                  onCheckedChange={handleEnabledChange}
                  disabled={enablementPending || isInvalid}
                  aria-label={toggleAriaLabel}
                />
              </Section>
            )}
            {item.source === "builtin" ? (
              item.is_available ? (
                <Badge title={t("skill.tags.builtin.label")} color="info" />
              ) : (
                <Badge
                  title={t("skill.tags.unavailable.label")}
                  color="pending"
                />
              )
            ) : isInvalid ? (
              <Badge title={t("skill.tags.invalid.label")} color="pending" />
            ) : dependency ? (
              <Badge title={t("skill.tags.appSkill.label")} color="info" />
            ) : null}
            {canEdit && hasUnpublishedChanges(item.skill) && (
              <Badge
                title={t("skill.tags.unpublished.label")}
                color="warning"
                tooltip={t("skill.tags.unpublished.tooltip", {
                  number: item.skill.published_version_number ?? 0,
                })}
              />
            )}
            {canEdit && item.skill.current_version_number !== null && (
              <Badge
                title={t("skill.tags.version.label", {
                  number: item.skill.current_version_number,
                })}
                tooltip={t("skill.tags.version.tooltip", {
                  number: item.skill.current_version_number,
                })}
              />
            )}
            {item.source === "custom" && (
              <Badge
                title={t(
                  item.skill.public_permission !== null
                    ? "skill.tags.organization.label"
                    : item.skill.is_personal
                      ? "skill.tags.personal.label"
                      : "skill.tags.shared.label"
                )}
                color={item.skill.is_personal ? "default" : "info"}
              />
            )}
          </Section>
        </Section>
      </Card>
    </Tooltip>
  );
}
