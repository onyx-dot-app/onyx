"use client";

import { useCallback, type MouseEvent } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  LineItemButton,
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
  SvgEye,
  SvgPlug,
  SvgShare,
  SvgTrash,
  SvgUser,
} from "@opal/icons";
import { useSkillPresentation } from "@/lib/skills/hooks";
import type {
  CustomSkill,
  SkillExternalAppDependency,
} from "@/lib/skills/types";
import { cn } from "@opal/utils";
import SkillVersionLabel from "@/sections/skills/SkillVersionLabel";
import SkillMarketplaceLabel from "@/sections/skills/SkillMarketplaceLabel";

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

  const handleClick = useCallback(() => {
    onClick?.(item);
  }, [onClick, item]);

  const {
    canDelete,
    isSynced,
    isRequired,
    authorTitle,
    dependency,
    isDependencyUnavailable,
    isSelectedDependencyUnavailable,
    isInactive,
    isInvalid,
    isBuiltinUnavailable,
    dependencyStatus,
    tooltip,
    canEdit,
    canShare,
    toggleAriaLabel,
  } = useSkillPresentation(item, hasEnabledNameConflict);

  const handleEditClick = (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    if (item.source === "custom") {
      onEdit?.(item);
    }
  };

  const handleEnabledChange = (enabled: boolean) => {
    onEnabledChange?.(item, enabled);
  };

  return (
    <Tooltip tooltip={tooltip} side="top">
      <Card
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
          height="auto"
          gap={1}
          padding={1}
          alignItems="stretch"
          justifyContent="start"
          className={cn(
            "min-h-24",
            isSelectedDependencyUnavailable && "opacity-50"
          )}
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
              className="min-w-0 flex-1"
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
              <LineItemButton
                font="main-ui-body"
                title={item.name}
                titleMaxLines={1}
                icon={selection ? undefined : SvgBlocks}
                aria-label={item.name}
                onClick={(event) => {
                  event.stopPropagation();
                  handleClick();
                }}
              />
            </Section>
            {item.source === "custom" &&
            (canEdit || canDelete) &&
            !selection?.checked ? (
              <Section
                flexDirection="row"
                justifyContent="start"
                width="fit"
                height="auto"
                gap={1}
                className="opacity-0 transition-opacity group-hover/SkillCard:opacity-100 group-focus-within/SkillCard:opacity-100 no-hover:opacity-100"
              >
                {canShare && onShare && (
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
                {canEdit && (
                  <Button
                    prominence="secondary"
                    size="sm"
                    icon={isSynced ? SvgEye : SvgEdit}
                    tooltip={
                      isSynced
                        ? skillCopy("synced.view")
                        : t("skill.edit.tooltip")
                    }
                    aria-label={
                      isSynced
                        ? skillCopy("synced.view")
                        : t("skill.edit.tooltip")
                    }
                    onClick={handleEditClick}
                  />
                )}
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
            {item.source === "custom" && (
              <SkillVersionLabel version={item.skill.current_version_number} />
            )}
            {item.source === "custom" && item.skill.marketplace && (
              <SkillMarketplaceLabel marketplace={item.skill.marketplace} />
            )}
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
                title={skillCopy("modals.share.installation.required")}
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
