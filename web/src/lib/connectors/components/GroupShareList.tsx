"use client";

import { useField } from "formik";
import { useTranslations } from "next-intl";
import {
  Button,
  InputSingleComboBox,
  Table,
  Text,
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

interface GroupShareListProps {
  /** Formik field holding the selected group ids. */
  name: "groups" | "data_access_group_ids";
  placeholder: string;
  /** Fixed rows shown before the selected groups (e.g. "Admins"). */
  lockedRows?: GroupShareLockedRow[];
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
      weight: 40,
      sortable: false,
      hideable: false,
      cell: (groupName) => (
        <Text font="main-ui-body" color="text-04">
          {groupName}
        </Text>
      ),
    },
    {
      kind: "data",
      field: "memberCount",
      title: t("table.members"),
      weight: 20,
      sortable: false,
      hideable: false,
      cell: (count) =>
        count === undefined ? null : (
          <Text font="secondary-body" color="text-03">
            {t("memberCount", { count })}
          </Text>
        ),
    },
    ...(hasLockedRows
      ? [
          {
            kind: "display",
            id: "note",
            width: { weight: 20 },
            hideable: false,
            alignment: "right",
            cell: (row) =>
              row.note ? (
                <Content
                  icon={row.icon}
                  title={row.note}
                  sizePreset="secondary"
                  variant="body"
                  orientation="reverse"
                  color="muted"
                />
              ) : null,
          } satisfies TableColumn<GroupShareRow>,
        ]
      : []),
    {
      kind: "actions",
      showColumnVisibility: false,
      showSorting: false,
      cell: (row) =>
        row.groupId === undefined ? null : (
          <Button
            icon={SvgX}
            size="sm"
            prominence="internal"
            tooltip={t("remove.tooltip", { name: row.name })}
            disabled={disabled}
            onClick={() =>
              setGroups(field.value.filter((id) => id !== row.groupId))
            }
          />
        ),
    },
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
