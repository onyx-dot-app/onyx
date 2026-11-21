"use client";

import { useState } from "react";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import {
  Button,
  Dropdown,
  LineItemButton,
  useCreateModal,
  type DropdownMenuItem,
} from "@opal/components";
import { toast } from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";
import {
  SvgCheckCircle,
  SvgPlus,
  SvgShare,
  SvgSort,
  SvgTrash,
  SvgXCircle,
} from "@opal/icons";
import { useNavigation } from "@opal/navigation";
import useUserSkills from "@/hooks/useUserSkills";
import { newSkillHref, pluginHref, skillHref } from "@/lib/customize/paths";
import {
  SKILL_GROUPS,
  groupSkills,
  visibleSkills,
  type SkillGroup,
  type SkillSort,
  type SkillStatusFilter,
} from "@/lib/customize/skills";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { useSettings } from "@/lib/settings/hooks";
import { deleteUserSkill } from "@/lib/skills/api";
import { hasUnpublishedChanges } from "@/lib/skills/sharing";
import {
  useSkillEnablement,
  type SkillEnablement,
  useRefreshSkillLists,
} from "@/lib/skills/hooks";
import type { Skill } from "@/lib/skills/types";
import { needsAttention } from "@/lib/plugins/needs";
import { Permission } from "@/lib/types";
import { useUser } from "@/providers/UserProvider";
import CustomizeLayout from "@/sections/customize/CustomizeLayout";
import AddSkillMenu from "@/sections/customize/AddSkillMenu";
import {
  CustomizeEmpty,
  CustomizeGroup,
  CustomizeRowActions,
  StatusFilter,
} from "@/sections/customize/CustomizeList";
import { skillIcon } from "@/sections/customize/skillIcon";
import { ConfirmEntityModal } from "@/sections/modals/ConfirmEntityModal";
import SkillPreviewModal from "@/sections/modals/SkillPreviewModal";
import ShareSkillModal from "@/sections/modals/skills/ShareSkillModal";
import SkillSwitchModal from "@/sections/modals/skills/SkillSwitchModal";
import PluginTurnOnModal from "@/sections/modals/plugins/PluginTurnOnModal";
import SkillReviewRequests from "@/sections/skills/SkillReviewRequests";

const RECENT_DAYS = 7;
const DAY_MS = 24 * 60 * 60 * 1000;

function canEdit(skill: Skill): boolean {
  return (
    skill.user_permission === "OWNER" || skill.user_permission === "EDITOR"
  );
}

interface SkillRowProps {
  skill: Skill;
  group: SkillGroup;
  enablement: SkillEnablement;
  onOpen: (skill: Skill) => void;
  onShare: (skill: Skill) => void;
  onRemove: (skill: Skill) => void;
}

function SkillRow({
  skill,
  group,
  enablement,
  onOpen,
  onShare,
  onRemove,
}: SkillRowProps) {
  const t = useTranslations("customize.skills");
  const cardCopy = useTranslations("cards");
  const format = useFormatter();
  const enabled = enablement.enabledOf(skill);
  const busy = enablement.isPending(skill.id);
  const updated = skill.updated_at ? new Date(skill.updated_at) : null;
  const now = new Date();
  const date =
    updated === null
      ? null
      : now.getTime() - updated.getTime() < RECENT_DAYS * DAY_MS
        ? format.relativeTime(updated, { now, style: "narrow" })
        : updated.getFullYear() === now.getFullYear()
          ? format.dateTime(updated, { month: "short", day: "numeric" })
          : format.dateTime(updated, {
              month: "short",
              day: "numeric",
              year: "numeric",
            });
  const source =
    group === "marketplace" && skill.marketplace
      ? t("source.marketplace", {
          name: skill.marketplace.name,
          scope: skill.marketplace.personal ? "personal" : "company",
        })
      : group === "mine"
        ? t("source.mine")
        : group === "organization"
          ? t("source.organization")
          : group === "builtin"
            ? t("source.builtin")
            : skill.owner
              ? t("source.sharedBy", { email: skill.owner.email })
              : t("source.shared");
  const menu: DropdownMenuItem[] = [
    ...(skill.can_toggle
      ? [
          {
            kind: "action" as const,
            id: "toggle",
            icon: enabled ? SvgXCircle : SvgCheckCircle,
            title: enabled ? t("menu.turnOff") : t("menu.turnOn"),
            disabled: busy,
            onSelect: () => void enablement.setEnabled(skill, !enabled),
          },
        ]
      : []),
    ...(skill.source === "custom" && canEdit(skill)
      ? [
          {
            kind: "action" as const,
            id: "share",
            icon: SvgShare,
            title: t("menu.share"),
            onSelect: () => onShare(skill),
          },
        ]
      : []),
    ...(skill.source === "custom" && skill.can_delete
      ? [
          {
            kind: "group" as const,
            items: [
              {
                kind: "action" as const,
                id: "remove",
                icon: SvgTrash,
                title: t("menu.remove"),
                danger: true,
                onSelect: () => onRemove(skill),
              },
            ],
          },
        ]
      : []),
  ];
  return (
    <LineItemButton
      icon={skillIcon(skill)}
      title={skill.name}
      titleMaxLines={1}
      description={
        skill.description
          ? t("subtitle", { source, description: skill.description })
          : source
      }
      descriptionMaxLines={1}
      badge={
        skill.is_valid === false
          ? { title: t("tag.invalid"), color: "error" }
          : !enabled
            ? { title: t("tag.off") }
            : skill.required_for_user
              ? { title: t("tag.required"), color: "info" }
              : skill.pending_version_number !== null && canEdit(skill)
                ? { title: t("tag.pending"), color: "warning" }
                : canEdit(skill) && hasUnpublishedChanges(skill)
                  ? {
                      title: cardCopy("skill.tags.unpublished.label"),
                      color: "warning",
                      tooltip: cardCopy("skill.tags.unpublished.tooltip", {
                        number: skill.published_version_number ?? 0,
                      }),
                    }
                  : undefined
      }
      aria-label={t("open", { name: skill.name })}
      onClick={() => onOpen(skill)}
      rightChildren={
        <CustomizeRowActions
          turnOn={
            !enabled && skill.can_toggle
              ? {
                  label: t("menu.turnOn"),
                  disabled: busy,
                  onClick: () => void enablement.setEnabled(skill, true),
                }
              : undefined
          }
          date={date}
          menuLabel={t("menu.label", { name: skill.name })}
          menu={menu}
        />
      }
    />
  );
}

export default function CustomizeSkillsPage() {
  const t = useTranslations("customize.skills");
  const skillCopy = useTranslations("skills");
  const locale = useLocale();
  const navigation = useNavigation();
  const settings = useSettings();
  const { user, isAdmin } = useUser();
  const revalidate = useRefreshSkillLists();
  const { isGlobalHolder: canManageOrgSkills } = usePermissionAuthority(
    Permission.MANAGE_PLUGINS
  );
  const { data, error, isLoading, refresh } = useUserSkills();
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<SkillStatusFilter>("all");
  const [sort, setSort] = useState<SkillSort>("updated");
  const removeModal = useCreateModal();
  const [removeTarget, setRemoveTarget] = useState<Skill | null>(null);
  const [removing, setRemoving] = useState(false);
  const [shareTarget, setShareTarget] = useState<Skill | null>(null);
  const [preview, setPreview] = useState<Skill | null>(null);

  const craftEnabled = settings.onyx_craft_enabled === true;
  const all = data ? visibleSkills(data, craftEnabled) : [];
  const [turnedOn, setTurnedOn] = useState<Skill | null>(null);
  const enablement = useSkillEnablement(all, refresh, (skill) => {
    if (needsAttention(skill.plugin?.needs ?? [])) setTurnedOn(skill);
  });
  const groups = data
    ? groupSkills(data, {
        userId: user?.id ?? null,
        craftEnabled,
        query,
        status,
        sort,
        locale,
      })
    : null;
  const shownCount = groups
    ? SKILL_GROUPS.reduce((count, group) => count + groups[group].length, 0)
    : 0;

  function open(skill: Skill): void {
    if (skill.source === "builtin") setPreview(skill);
    else if (skill.kind === "plugin") navigation.go(pluginHref(skill.id));
    else navigation.go(skillHref(skill.id));
  }

  async function remove(): Promise<void> {
    if (!removeTarget || removing) return;
    setRemoving(true);
    try {
      await deleteUserSkill(removeTarget.id);
      revalidate();
      removeModal.toggle(false);
      toast.success(
        skillCopy("editor.toasts.deleted", { name: removeTarget.name })
      );
    } catch (failure) {
      toast.error(
        failure instanceof Error
          ? failure.message
          : skillCopy("editor.toasts.deleteFailed")
      );
    } finally {
      setRemoving(false);
    }
  }

  const controls = (
    <>
      <StatusFilter
        value={status}
        onChange={setStatus}
        allLabel={t("filter.all")}
      />
      <Dropdown align="end" width={60}>
        <Dropdown.Trigger asChild>
          <Button
            prominence="tertiary"
            icon={SvgSort}
            aria-label={t("sort.label")}
            tooltip={t("sort.label")}
          />
        </Dropdown.Trigger>
        <Dropdown.Data
          label={t("sort.label")}
          items={[
            { kind: "option", value: "updated", title: t("sort.updated") },
            { kind: "option", value: "name", title: t("sort.name") },
          ]}
          value={sort}
          onSelect={(option) =>
            setSort(option.value === "name" ? "name" : "updated")
          }
        />
      </Dropdown>
      <AddSkillMenu />
    </>
  );

  return (
    <CustomizeLayout
      tab="skills"
      query={query}
      onQueryChange={setQuery}
      controls={controls}
      loading={isLoading}
      error={error ? t("loadFailed") : false}
    >
      {canManageOrgSkills && !isAdmin && (
        <SkillReviewRequests onReviewed={revalidate} />
      )}
      {groups && shownCount === 0 ? (
        <CustomizeEmpty
          illustration={SvgNoResult}
          title={all.length > 0 ? t("noMatches.title") : t("empty.title")}
          description={
            all.length > 0 ? t("noMatches.description") : t("empty.description")
          }
          action={
            all.length > 0 ? (
              <Button
                prominence="secondary"
                onClick={() => {
                  setQuery("");
                  setStatus("all");
                }}
              >
                {t("noMatches.clear")}
              </Button>
            ) : (
              <Button
                icon={SvgPlus}
                onClick={() => navigation.go(newSkillHref())}
              >
                {t("add.create")}
              </Button>
            )
          }
        />
      ) : (
        groups &&
        SKILL_GROUPS.map((group) => (
          <CustomizeGroup key={group} title={t(`groups.${group}`)}>
            {groups[group].map((skill) => (
              <SkillRow
                key={skill.id}
                skill={skill}
                group={group}
                enablement={enablement}
                onOpen={open}
                onShare={setShareTarget}
                onRemove={(target) => {
                  setRemoveTarget(target);
                  removeModal.toggle(true);
                }}
              />
            ))}
          </CustomizeGroup>
        ))
      )}

      <SkillSwitchModal enablement={enablement} />
      {turnedOn && (
        <PluginTurnOnModal
          plugin={turnedOn}
          onClose={() => setTurnedOn(null)}
        />
      )}
      {shareTarget && (
        <ShareSkillModal
          mode="edit"
          skillId={shareTarget.id}
          fallbackTitle={shareTarget.name}
          open
          onClose={() => setShareTarget(null)}
          onSaved={revalidate}
        />
      )}
      <SkillPreviewModal
        open={preview !== null}
        skillId={preview?.id ?? null}
        fallbackTitle={preview?.name}
        unavailableReason={
          preview && preview.source === "builtin" && !preview.is_available
            ? (preview.unavailable_reason ??
              skillCopy("page.preview.unavailableFallback"))
            : null
        }
        onClose={() => setPreview(null)}
      />
      <removeModal.Provider>
        {removeTarget && (
          <ConfirmEntityModal
            danger
            entityType={skillCopy("editor.deleteModal.entityType")}
            entityName={removeTarget.name}
            additionalDetails={skillCopy("editor.delete.description")}
            actionButtonText={skillCopy(
              removing
                ? "editor.deleteModal.pendingLabel"
                : "editor.deleteModal.label"
            )}
            onClose={() => {
              if (!removing) removeModal.toggle(false);
            }}
            onSubmit={() => void remove()}
          />
        )}
      </removeModal.Provider>
    </CustomizeLayout>
  );
}
