"use client";

import { useField } from "formik";
import { useTranslations } from "next-intl";
import {
  Button,
  InputSingleComboBox,
  Table,
  type TableColumn,
} from "@opal/components";
import { Content, InputErrorText, Section } from "@opal/layouts";
import { SvgUsers, SvgX } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import { useUserGroups } from "@/lib/hooks";

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

interface GroupShareListProps {
  /** Formik field holding the selected group ids. */
  name: "groups" | "data_access_group_ids";
  placeholder: string;
  /** Fixed rows shown before the selected groups (e.g. "Admins"). */
  lockedRows?: GroupShareLockedRow[];
  /**
   * Each picked group's trailing control, in place of the remove button,
   * e.g. a role menu. `remove` drops the group.
   */
  rowAction?: (group: GroupShareGroup, remove: () => void) => React.ReactNode;
  disabled?: boolean;
}

/**
 * A group combo box over a table of the groups already added. Each row shows
 * the group's member count and a remove button.
 */
export default function GroupShareList({
  name,
  placeholder,
  lockedRows = [],
  rowAction,
  disabled,
}: GroupShareListProps) {
  const t = useTranslations("admin.connector.groupRestriction");
  const { data: userGroups, isLoading, error } = useUserGroups();
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
        options={options}
        placeholder={placeholder}
        disabled={disabled || isLoading || loadFailed}
      />
      {loadFailed && <InputErrorText>{t("loadError")}</InputErrorText>}
      {rows.length > 0 && (
        <Table
          items={rows}
          columns={columns}
          getRowId={(row) => row.id}
          pageSize={Infinity}
          prominence="secondary"
          showHeader={false}
        />
      )}
      {meta.touched && meta.error && (
        <InputErrorText>{meta.error}</InputErrorText>
      )}
    </Section>
  );
}
