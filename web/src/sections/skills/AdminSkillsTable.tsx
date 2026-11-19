"use client";

import { useFormatter, useTranslations } from "next-intl";
import {
  Button,
  Dropdown,
  InputSwitch,
  Table,
  Text,
  type TableColumn,
} from "@opal/components";
import { Content, Section } from "@opal/layouts";
import { SvgMoreHorizontal, SvgShare, SvgTrash } from "@opal/icons";
import { useInstallationPolicyCopy } from "@/lib/skills/hooks";
import { hasUnpublishedChanges } from "@/lib/skills/sharing";
import type { CustomSkill } from "@/lib/skills/types";
import { skillIcon } from "@/sections/customize/skillIcon";

interface AdminSkillsTableProps {
  skills: CustomSkill[];
  selectedIds: ReadonlySet<string>;
  onSelectionChange: (ids: ReadonlySet<string>) => void;
  busy: boolean;
  isPending: (id: string) => boolean;
  enabledOf: (skill: CustomSkill) => boolean;
  onEnabledChange: (skill: CustomSkill, enabled: boolean) => void;
  onOpen: (skill: CustomSkill) => void;
  onShare: (skill: CustomSkill) => void;
  onDelete: (skill: CustomSkill) => void;
}

export default function AdminSkillsTable({
  skills,
  selectedIds,
  onSelectionChange,
  busy,
  isPending,
  enabledOf,
  onEnabledChange,
  onOpen,
  onShare,
  onDelete,
}: AdminSkillsTableProps) {
  const t = useTranslations("skills.adminTable");
  const skillCopy = useTranslations("skills");
  const tagCopy = useTranslations("customize.skills.tag");
  const cardCopy = useTranslations("cards");
  const format = useFormatter();
  const policyCopy = useInstallationPolicyCopy();

  const columns: TableColumn<CustomSkill>[] = [
    {
      kind: "qualifier",
      selectLabel: (skill) => t("select", { name: skill.name }),
    },
    {
      kind: "data",
      field: "name",
      title: t("columns.name"),
      weight: 34,
      truncate: true,
      cell: (name, skill) => (
        <Content
          icon={skillIcon(skill)}
          title={name}
          description={skill.description}
          titleMaxLines={1}
          descriptionMaxLines={1}
          badge={
            skill.is_valid === false
              ? { title: tagCopy("invalid"), color: "error" }
              : skill.installation_policy === "REQUIRED"
                ? { title: tagCopy("required"), color: "info" }
                : skill.pending_version_number !== null
                  ? { title: tagCopy("pending"), color: "warning" }
                  : hasUnpublishedChanges(skill)
                    ? {
                        title: cardCopy("skill.tags.unpublished.label"),
                        color: "warning",
                      }
                    : undefined
          }
        />
      ),
    },
    {
      kind: "display",
      id: "source",
      title: t("columns.source"),
      width: { weight: 18 },
      cell: (skill) => (
        <Text font="main-ui-body" color="text-03" maxLines={1}>
          {skill.published_version_number !== null
            ? t("organizationLibrary")
            : (skill.owner?.email ?? t("noOwner"))}
        </Text>
      ),
    },
    {
      kind: "display",
      id: "version",
      title: t("columns.version"),
      width: { weight: 12 },
      cell: (skill) => (
        <Text font="main-ui-body" color="text-03" maxLines={1}>
          {t("version", {
            current: skill.current_version_number ?? 1,
            published:
              skill.published_version_number === null
                ? "none"
                : String(skill.published_version_number),
          })}
        </Text>
      ),
    },
    {
      kind: "display",
      id: "audience",
      title: t("columns.audience"),
      width: { weight: 20 },
      cell: (skill) => (
        <Section gap={0} alignItems="stretch" height="auto">
          <Text font="main-ui-body" color="text-03" maxLines={1}>
            {skill.public_permission === null
              ? skill.is_personal
                ? t("private")
                : t("shared")
              : policyCopy.label(skill.installation_policy, {
                  scope: "skill",
                  policy: skill.default_installation_policy,
                })}
          </Text>
          {skill.group_summaries.length > 0 && (
            <Text
              font="secondary-body"
              color="text-03"
              maxLines={1}
              overflowTooltip
            >
              {skillCopy("groups.card", {
                groups: format.list(
                  skill.group_summaries.map((summary) =>
                    summary.installation_policy === null
                      ? summary.group_name
                      : skillCopy("groups.entry", {
                          name: summary.group_name,
                          policy: policyCopy.label(summary.installation_policy),
                        })
                  )
                ),
              })}
            </Text>
          )}
        </Section>
      ),
    },
    {
      kind: "display",
      id: "enabled",
      width: { fixed: 64 },
      cell: (skill) => (
        <Section
          width="auto"
          height="auto"
          onClick={(event) => event.stopPropagation()}
        >
          <InputSwitch
            aria-label={skill.name}
            checked={enabledOf(skill)}
            disabled={busy || isPending(skill.id) || !skill.can_toggle}
            onCheckedChange={(checked) => onEnabledChange(skill, checked)}
          />
        </Section>
      ),
    },
    {
      kind: "actions",
      cell: (skill) => (
        <Section
          width="auto"
          height="auto"
          onClick={(event) => event.stopPropagation()}
        >
          <Dropdown align="end">
            <Dropdown.Trigger asChild>
              <Button
                size="sm"
                prominence="tertiary"
                icon={SvgMoreHorizontal}
                aria-label={t("menu", { name: skill.name })}
                tooltip={t("menu", { name: skill.name })}
              />
            </Dropdown.Trigger>
            <Dropdown.Data
              label={t("menu", { name: skill.name })}
              items={[
                ...(skill.user_permission === "OWNER" ||
                skill.user_permission === "EDITOR"
                  ? [
                      {
                        kind: "action" as const,
                        id: "share",
                        icon: SvgShare,
                        title: t("share"),
                        onSelect: () => onShare(skill),
                      },
                    ]
                  : []),
                {
                  kind: "group",
                  items: [
                    {
                      kind: "action",
                      id: "delete",
                      icon: SvgTrash,
                      title: t("delete"),
                      danger: true,
                      disabled: !skill.can_delete,
                      onSelect: () => onDelete(skill),
                    },
                  ],
                },
              ]}
            />
          </Dropdown>
        </Section>
      ),
    },
  ];

  return (
    <Table
      label={t("label")}
      items={skills}
      columns={columns}
      getRowId={(skill) => skill.id}
      pageSize={false}
      selectionBehavior="multi-select"
      values={selectedIds}
      onSelectionChange={onSelectionChange}
      onRowClick={onOpen}
      getRowLabel={(skill) => t("open", { name: skill.name })}
    />
  );
}
