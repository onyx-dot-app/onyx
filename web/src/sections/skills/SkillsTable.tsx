"use client";

import { useMemo } from "react";
import useScreenSize from "@opal/hooks/useScreenSize";
import { useTranslations } from "next-intl";
import {
  Badge,
  Button,
  Dropdown,
  InputSwitch,
  Table,
  Text,
  type TableColumn,
  type DropdownMenuItem,
} from "@opal/components";
import { Section } from "@opal/layouts";
import { SvgEdit, SvgMoreHorizontal, SvgShare, SvgTrash } from "@opal/icons";
import type {
  CustomSkillCardItem,
  SkillCardProps,
} from "@/sections/cards/SkillCard";
import { useSkillPresentation } from "@/lib/skills/hooks";

type SkillTableItem = SkillCardProps & {
  item: CustomSkillCardItem;
  showDescription: boolean;
};

interface SkillsTableProps {
  items: CustomSkillCardItem[];
  selectedIds: ReadonlySet<string>;
  onSelectionChange: (values: ReadonlySet<string>) => void;
  selectionDisabled: boolean;
  getItemProps: (item: CustomSkillCardItem) => SkillCardProps;
}

function SkillName({
  item,
  hasEnabledNameConflict,
  showDescription,
}: SkillTableItem) {
  const t = useTranslations("cards");
  const { isMobile } = useScreenSize();
  const { isInvalid, dependencyStatus, tooltip } = useSkillPresentation(
    item,
    hasEnabledNameConflict
  );
  return (
    <Section
      height="auto"
      gap={0}
      alignItems="stretch"
      width={0}
      className="min-w-full"
    >
      <Text
        font="main-ui-body"
        color="text-05"
        as="p"
        maxLines={
          isMobile && !showDescription && !isInvalid && !dependencyStatus
            ? 2
            : 1
        }
        overflowTooltip
      >
        {item.name}
      </Text>
      {(!isMobile || showDescription || isInvalid || dependencyStatus) && (
        <Text
          font="secondary-body"
          color={isInvalid ? "status-warning-05" : "text-03"}
          as="p"
          maxLines={1}
          overflowTooltip
          tooltip={tooltip}
        >
          {isInvalid
            ? t("skill.invalid.description")
            : (dependencyStatus ?? item.description)}
        </Text>
      )}
    </Section>
  );
}

function SkillActions({
  item,
  onEdit,
  onShare,
  onDelete,
  onEnabledChange,
  enablementPending,
}: SkillCardProps) {
  const t = useTranslations("skills");
  const cards = useTranslations("cards");
  const {
    canEdit,
    canManageCompanySkills,
    isRequired,
    isInvalid,
    isDependencyUnavailable,
    toggleAriaLabel,
    tooltip,
  } = useSkillPresentation(item);
  const actions: DropdownMenuItem[] = [];
  if (item.source === "custom" && canEdit) {
    if (onShare)
      actions.push({
        kind: "action",
        id: "share",
        icon: SvgShare,
        title: t("editor.management.sharing.edit.label"),
        onSelect: () => onShare(item),
      });
    if (onEdit)
      actions.push({
        kind: "action",
        id: "edit",
        icon: SvgEdit,
        title: cards("skill.edit.tooltip"),
        onSelect: () => onEdit(item),
      });
    if (onDelete && (!isRequired || canManageCompanySkills))
      actions.push({
        kind: "action",
        id: "delete",
        icon: SvgTrash,
        title: t("editor.delete.button.label"),
        danger: true,
        onSelect: () => onDelete(item),
      });
  }
  return (
    <Section
      flexDirection="row"
      gap={1}
      height="auto"
      justifyContent="end"
      onClick={(event) => event.stopPropagation()}
    >
      {item.can_toggle && (
        <InputSwitch
          checked={item.enabled}
          aria-label={toggleAriaLabel}
          title={tooltip}
          disabled={
            enablementPending ||
            isInvalid ||
            (isDependencyUnavailable && !item.enabled)
          }
          onCheckedChange={(enabled) => onEnabledChange?.(item, enabled)}
        />
      )}
      {actions.length > 0 && (
        <Dropdown align="end" disabled={enablementPending}>
          <Dropdown.Trigger asChild>
            <Button
              size="md"
              prominence="tertiary"
              icon={SvgMoreHorizontal}
              aria-label={t("bulk.moreActionsForSkill", { name: item.name })}
              tooltip={t("bulk.moreActionsForSkill", { name: item.name })}
              disabled={enablementPending}
            />
          </Dropdown.Trigger>
          <Dropdown.Data label={item.name} items={actions} />
        </Dropdown>
      )}
    </Section>
  );
}

export default function SkillsTable({
  items,
  selectedIds,
  onSelectionChange,
  selectionDisabled,
  getItemProps,
}: SkillsTableProps) {
  const t = useTranslations("skills");
  const cards = useTranslations("cards");
  const { isMobile } = useScreenSize();
  const duplicateNames = useMemo(() => {
    const seen = new Set<string>();
    const duplicates = new Set<string>();
    for (const item of items) {
      if (seen.has(item.name)) duplicates.add(item.name);
      seen.add(item.name);
    }
    return duplicates;
  }, [items]);
  const columns = useMemo<TableColumn<SkillTableItem>[]>(
    () => [
      { kind: "qualifier", content: "checkbox" },
      {
        kind: "display",
        id: "skill",
        title: t("page.header.title"),
        width: { weight: 48, minWidth: isMobile ? 88 : 160 },
        hideable: false,
        cell: (props) => <SkillName {...props} />,
      },
      {
        kind: "display",
        id: "access",
        title: t("modals.share.accessTitle"),
        width: { weight: 25, minWidth: 148 },
        hideable: false,
        cell: ({ item: { skill } }) => (
          <Section
            height="auto"
            gap={1}
            alignItems="start"
            width={0}
            className="min-w-full"
          >
            <Section
              width="auto"
              height="auto"
              className="rounded-04 border border-border-02"
            >
              <Badge
                size={5}
                titleColor="text-04"
                title={cards(
                  skill.public_permission !== null
                    ? "skill.tags.organization.label"
                    : skill.is_personal
                      ? "skill.tags.personal.label"
                      : "skill.tags.shared.label"
                )}
              />
            </Section>
            {skill.group_shares.length > 0 && (
              <Text
                font="secondary-body"
                color="text-03"
                as="p"
                maxLines={1}
                overflowTooltip
              >
                {skill.group_shares.map((share) => share.group_name).join(", ")}
              </Text>
            )}
          </Section>
        ),
      },
      {
        kind: "display",
        id: "installation",
        title: t("modals.share.installation.title"),
        width: { weight: 24, minWidth: 156 },
        hideable: false,
        cell: ({ item: { skill } }) => (
          <Text
            font="secondary-body"
            color="text-04"
            maxLines={1}
            overflowTooltip
          >
            {t(
              skill.installation_policy === "REQUIRED"
                ? "modals.share.installation.required"
                : skill.installation_policy === "DEFAULT"
                  ? "modals.share.installation.default"
                  : "modals.share.installation.available"
            )}
          </Text>
        ),
      },
      {
        kind: "display",
        id: "actions",
        title: t(isMobile ? "bulk.personalSetting" : "bulk.enable"),
        width: { fixed: isMobile ? 80 : 104 },
        hideable: false,
        alignment: "right",
        cell: (props) => <SkillActions {...props} />,
      },
    ],
    [t, cards, isMobile]
  );
  const visibleColumns = useMemo(
    () =>
      isMobile
        ? columns.filter(
            (column) =>
              column.kind !== "display" ||
              (column.id !== "access" && column.id !== "installation")
          )
        : columns,
    [columns, isMobile]
  );
  return (
    <Table
      label={t("page.header.title")}
      items={items.map((item) => ({
        ...getItemProps(item),
        item,
        showDescription: duplicateNames.has(item.name),
      }))}
      columns={visibleColumns}
      getRowId={({ item }) => item.id}
      values={selectedIds}
      selectionBehavior="multi-select"
      selectionDisabled={selectionDisabled}
      onSelectionChange={onSelectionChange}
      selectAllLabel={t("bulk.selectAll")}
      getRowSelectionLabel={({ item }) =>
        t("bulk.selectSkill", { name: item.name })
      }
      pageSize={false}
      onRowClick={({ item, onClick }) => onClick?.(item)}
      getRowLabel={({ item }) => item.name}
    />
  );
}
