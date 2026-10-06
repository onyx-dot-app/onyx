"use client";

import { useField } from "formik";
import { useTranslations } from "next-intl";
import { Button, InputSingleComboBox } from "@opal/components";
import { AttachmentItem, InputErrorText, Section } from "@opal/layouts";
import { SvgUsers, SvgX } from "@opal/icons";
import { useUserGroups } from "@/lib/hooks";

interface GroupShareListProps {
  /** Formik field holding the selected group ids. */
  name: "groups" | "data_access_group_ids";
  placeholder: string;
  /** A fixed row shown before the selected groups (e.g. "Admins"). */
  leadingRow?: React.ReactNode;
  disabled?: boolean;
}

/**
 * A group combo box over the rows of the groups already added. Each row shows
 * the group's member count and a remove button.
 */
export default function GroupShareList({
  name,
  placeholder,
  leadingRow,
  disabled,
}: GroupShareListProps) {
  const t = useTranslations("admin.connector.groupRestriction");
  const { data: userGroups, isLoading, error } = useUserGroups();
  // Without the groups there is nothing to pick from, and the rows already
  // added cannot show; say so rather than show an empty picker.
  const loadFailed = !isLoading && !!error;
  const [field, meta, helpers] = useField<number[]>(name);

  const selectedIds = new Set(field.value);
  const selectedGroups = (userGroups ?? []).filter((group) =>
    selectedIds.has(group.id)
  );
  const options = (userGroups ?? [])
    .filter((group) => !selectedIds.has(group.id))
    .map((group) => ({
      value: String(group.id),
      title: group.name,
      description: t("memberCount", { count: group.users.length }),
      icon: SvgUsers,
    }));

  function setGroups(ids: number[]) {
    void helpers.setTouched(true, false);
    void helpers.setValue(ids);
  }

  function addGroup(value: string) {
    const id = Number(value);
    if (!Number.isInteger(id) || selectedIds.has(id)) return;
    setGroups([...field.value, id]);
  }

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
      {leadingRow}
      {selectedGroups.length > 0 && (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {selectedGroups.map((group) => (
            <AttachmentItem
              key={group.id}
              prominence="secondary"
              icon={SvgUsers}
              title={group.name}
              description={t("memberCount", { count: group.users.length })}
              rightChildren={
                <Button
                  icon={SvgX}
                  size="sm"
                  prominence="internal"
                  tooltip={t("remove.tooltip", { name: group.name })}
                  disabled={disabled}
                  onClick={() =>
                    setGroups(field.value.filter((id) => id !== group.id))
                  }
                />
              }
            />
          ))}
        </div>
      )}
      {meta.touched && meta.error && (
        <InputErrorText>{meta.error}</InputErrorText>
      )}
    </Section>
  );
}
