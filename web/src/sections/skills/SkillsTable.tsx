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
import {
  SvgEdit,
  SvgEye,
  SvgMoreHorizontal,
  SvgShare,
  SvgTrash,
} from "@opal/icons";
import type {
  CustomSkillCardItem,
  SkillCardProps,
} from "@/sections/cards/SkillCard";
import {
  useInstallationPolicyOptions,
  useSkillPresentation,
} from "@/lib/skills/hooks";
import SkillVersionLabel from "@/sections/skills/SkillVersionLabel";
import SkillMarketplaceLabel from "@/sections/skills/SkillMarketplaceLabel";
import SkillGroupSummaries from "@/sections/skills/SkillGroupSummaries";

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
        wordWrap="wrap-anywhere"
        maxLines={
          isMobile && !showDescription && !isInvalid && !dependencyStatus
            ? 2
            : 1
        }
        overflowTooltip
      >
        {item.name}
      </Text>
      <SkillVersionLabel version={item.skill.current_version_number} />
      {(!isMobile || showDescription || isInvalid) && (
        <Text
          font="secondary-body"
          color={isInvalid ? "status-warning-05" : "text-03"}
          as="p"
          maxLines={1}
          overflowTooltip
          tooltip={tooltip}
        >
          {isInvalid ? t("skill.invalid.description") : item.description}
        </Text>
      )}
      {!isInvalid && dependencyStatus && (
        <Text
          font="secondary-body"
          color="text-03"
          as="p"
          maxLines={1}
          overflowTooltip
          tooltip={tooltip}
        >
          {dependencyStatus}
        </Text>
      )}
      {item.skill.marketplace && (
        <SkillMarketplaceLabel marketplace={item.skill.marketplace} />
      )}
      {isMobile && (
        <SkillGroupSummaries summaries={item.skill.group_summaries} compact />
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
    canShare,
    canDelete,
    isSynced,
    isInvalid,
    isDependencyUnavailable,
    toggleAriaLabel,
    tooltip,
  } = useSkillPresentation(item);
  const actions: DropdownMenuItem[] = [];
  if (item.source === "custom") {
    if (canShare && onShare)
      actions.push({
        kind: "action",
        id: "share",
        icon: SvgShare,
        title: t("editor.management.sharing.edit.label"),
        onSelect: () => onShare(item),
      });
    if (canEdit && onEdit)
      actions.push({
        kind: "action",
        id: "edit",
        icon: isSynced ? SvgEye : SvgEdit,
        title: isSynced ? t("synced.view") : cards("skill.edit.tooltip"),
        onSelect: () => onEdit(item),
      });
    if (onDelete && canDelete)
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
      wrap
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
  const installationOptions = useInstallationPolicyOptions();
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
        width: { weight: 40, minWidth: isMobile ? 88 : 160 },
        hideable: false,
        cell: (props) => <SkillName {...props} />,
      },
      {
        kind: "display",
        id: "access",
        title: t("modals.share.accessTitle"),
        width: { weight: 18, minWidth: 128 },
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
          </Section>
        ),
      },
      {
        kind: "display",
        id: "groups",
        title: t("groups.columnTitle"),
        width: { weight: 22, minWidth: 140 },
        hideable: false,
        cell: ({ item: { skill } }) => (
          <SkillGroupSummaries summaries={skill.group_summaries} />
        ),
      },
      {
        kind: "display",
        id: "installation",
        title: t("modals.share.installation.title"),
        width: { weight: 20, minWidth: 148 },
        hideable: false,
        cell: ({ item: { skill } }) => (
          <Text
            font="main-ui-body"
            color="text-04"
            maxLines={1}
            overflowTooltip
          >
            {
              installationOptions.find(
                ({ value }) => value === skill.installation_policy
              )?.label
            }
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
    [t, cards, isMobile, installationOptions]
  );
  const visibleColumns = useMemo(
    () =>
      isMobile
        ? columns.filter(
            (column) =>
              column.kind !== "display" ||
              (column.id !== "access" &&
                column.id !== "groups" &&
                column.id !== "installation")
          )
        : columns,
    [columns, isMobile]
  );
  return (
    <Table
      label={t("page.header.title")}
      rowHeight="content"
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
