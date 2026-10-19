"use client";

import { useField } from "formik";
import { useTranslations } from "next-intl";
import {
  Button,
  InputSingleComboBox,
  Tag,
  Table,
  type TableColumn,
} from "@opal/components";
import { Content, InputErrorText, Section } from "@opal/layouts";
import { SvgUsers, SvgX } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import { useUserGroups } from "@/lib/hooks";
import { useTierAtLeast, useTierLockedOptions } from "@/lib/tiers/hooks";
import { Tier } from "@/lib/tiers/types";

/** A fixed row shown before the picked groups, which cannot be removed. */
export interface GroupShareLockedRow {
  id: string;
  name: string;
  icon: IconFunctionComponent;
  memberCount?: number;
  /** Why the row is fixed, e.g. "Always shared". */
  note: string;
}

interface GroupShareRow {
  id: string;
  name: string;
  icon: IconFunctionComponent;
  memberCount?: number;
  /** Set on a locked row. */
  note?: string;
  /** Set on a picked group, which the remove button drops. */
  groupId?: number;
}

/** A picked group, as the row's trailing control sees it. */
export interface GroupShareGroup {
  id: number;
  name: string;
}

interface GroupShareListBaseProps {
  /** Formik field holding the selected group ids. */
  name: "groups" | "data_access_group_ids";
  label: string;
  placeholder: string;
  disabled?: boolean;
  /**
   * The tier groups need. Below it the workspace has no groups to pick, so
   * the picker offers only an upgrade link.
   */
  requiredTier?: Tier;
}

type GroupShareListProps = GroupShareListBaseProps &
  (
    | { variant: "pills"; lockedRows?: never; rowAction?: never }
    | {
        variant?: "rows";
        /** Fixed rows shown before the selected groups (e.g. "Admins"). */
        lockedRows?: GroupShareLockedRow[];
        /**
         * Each picked group's trailing control, in place of the remove button,
         * e.g. a role menu. `remove` drops the group.
         */
        rowAction?: (
          group: GroupShareGroup,
          remove: () => void
        ) => React.ReactNode;
      }
  );

/**
 * Search for groups, then show selections as table rows or removable pills.
 */
export default function GroupShareList({
  name,
  label,
  placeholder,
  lockedRows = [],
  rowAction,
  disabled,
  requiredTier = Tier.COMMUNITY,
  variant = "rows",
}: GroupShareListProps) {
  const t = useTranslations("admin.connector.groupRestriction");
  const locked: boolean = !useTierAtLeast(requiredTier);
  const lockForTier = useTierLockedOptions(requiredTier);
  // Below the tier the groups request is refused, so it is not sent.
  const { data: userGroups, isLoading, error } = useUserGroups(!locked);
  // Without the groups there is nothing to pick from, and the rows already
  // added cannot show; say so rather than show an empty picker.
  const loadFailed = !isLoading && !!error;
  const [field, meta, helpers] = useField<number[]>(name);

  const selectedIds = new Set(field.value);
  const options = (userGroups ?? [])
    .filter((group) => !selectedIds.has(group.id))
    .map((group) => ({
      value: String(group.id),
      title: group.name,
      description: t("memberCount", { count: group.users.length }),
      icon: SvgUsers,
    }));

  // Below the tier the fixed rows sit locked under the upgrade link, so the
  // list names what the plan adds to.
  const lockedOptions = lockedRows.map((row) => ({
    value: row.id,
    title: row.name,
    description:
      row.memberCount === undefined
        ? undefined
        : t("memberCount", { count: row.memberCount }),
    icon: row.icon,
  }));

  const rows: GroupShareRow[] = [
    ...lockedRows,
    ...(userGroups ?? [])
      .filter((group) => selectedIds.has(group.id))
      .map((group) => ({
        id: `group-${group.id}`,
        name: group.name,
        icon: SvgUsers,
        memberCount: group.users.length,
        groupId: group.id,
      })),
  ];

  function setGroups(ids: number[]) {
    void helpers.setTouched(true, false);
    void helpers.setValue(ids);
  }

  function removeGroup(groupId: number) {
    setGroups(field.value.filter((id) => id !== groupId));
  }

  function addGroup(value: string) {
    const id = Number(value);
    if (!Number.isInteger(id) || selectedIds.has(id)) return;
    setGroups([...field.value, id]);
  }

  const hasLockedRows = lockedRows.length > 0;
  const columns: TableColumn<GroupShareRow>[] = [
    {
      kind: "qualifier",
      content: "icon",
      icon: (row) => row.icon,
      background: true,
    },
    {
      kind: "data",
      field: "name",
      title: t("table.group"),
      weight: 60,
      sortable: false,
      hideable: false,
      cell: (groupName, row) => (
        <Content
          title={groupName}
          description={
            row.memberCount === undefined
              ? undefined
              : t("memberCount", { count: row.memberCount })
          }
          sizePreset="main-ui"
          variant="section"
        />
      ),
    },
    // The locked rows' note and the picked groups' own control share one
    // trailing column, so they line up.
    ...(hasLockedRows || rowAction
      ? [
          {
            kind: "display",
            id: "trailing",
            width: { weight: 20 },
            hideable: false,
            alignment: "right",
            cell: (row) => {
              if (row.note) {
                return (
                  <Content
                    icon={row.icon}
                    title={row.note}
                    sizePreset="secondary"
                    variant="body"
                    orientation="reverse"
                    color="muted"
                  />
                );
              }
              const { groupId } = row;
              if (groupId === undefined || !rowAction) return null;
              return rowAction({ id: groupId, name: row.name }, () =>
                removeGroup(groupId)
              );
            },
          } satisfies TableColumn<GroupShareRow>,
        ]
      : []),
    ...(rowAction
      ? []
      : [
          {
            kind: "actions",
            showColumnVisibility: false,
            showSorting: false,
            cell: (row) => {
              const { groupId } = row;
              return groupId === undefined ? null : (
                <Button
                  icon={SvgX}
                  size="sm"
                  prominence="internal"
                  tooltip={t("remove.tooltip", { name: row.name })}
                  disabled={disabled}
                  onClick={() => removeGroup(groupId)}
                />
              );
            },
          } satisfies TableColumn<GroupShareRow>,
        ]),
  ];

  return (
    <Section gap={2} alignItems="stretch" height="fit">
      <InputSingleComboBox
        value=""
        onValueChange={addGroup}
        options={locked ? lockForTier(lockedOptions) : options}
        placeholder={placeholder}
        disabled={disabled || isLoading || loadFailed}
      />
      {variant === "pills" && rows.length > 0 && (
        <div
          role="group"
          aria-label={label}
          className="flex max-h-40 flex-wrap gap-2 overflow-y-auto p-1"
        >
          {rows.map((row) => {
            const groupId = row.groupId;
            return groupId === undefined ? null : (
              <Tag
                key={row.id}
                title={row.name}
                icon={row.icon}
                size="md"
                onRemove={() => removeGroup(groupId)}
                disabled={disabled || isLoading || loadFailed}
              />
            );
          })}
        </div>
      )}
      {loadFailed && <InputErrorText>{t("loadError")}</InputErrorText>}
      {variant === "rows" && rows.length > 0 && (
        <Table
          label={label}
          items={rows}
          columns={columns}
          getRowId={(row) => row.id}
          pageSize={false}
          prominence="secondary"
          header={false}
        />
      )}
      {meta.touched && meta.error && (
        <InputErrorText>{meta.error}</InputErrorText>
      )}
    </Section>
  );
}
