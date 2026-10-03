"use client";

import { useField } from "formik";
import { useTranslations } from "next-intl";
import {
  Button,
  Card,
  EmptyMessageCard,
  InputSingleComboBox,
  InputSwitch,
} from "@opal/components";
import { ContentAction, InputHorizontal } from "@opal/layouts";
import { SvgUsers, SvgX } from "@opal/icons";
import { useUserGroups } from "@/lib/hooks";
import type { ConnectorGroupRestrictionFormValues } from "@/lib/connectors/accessType";

type FieldName = keyof ConnectorGroupRestrictionFormValues;

const RESTRICT_FIELD: FieldName = "restrict_access_to_groups";
const GROUP_IDS_FIELD: FieldName = "restriction_group_ids";

/**
 * Data-access restriction for a perm-synced connector: only members of the
 * chosen groups can read its documents, on top of the source's permissions.
 * Separate from the management-access groups, which decide who can configure
 * the connector.
 */
export function ConnectorGroupRestrictionPicker() {
  const t = useTranslations("admin.connector.groupRestriction");
  const { data: userGroups } = useUserGroups();
  const [restrict, , restrictHelpers] = useField<boolean>(RESTRICT_FIELD);
  const [groupIds, , groupIdsHelpers] = useField<number[]>(GROUP_IDS_FIELD);

  const selectedIds = new Set(groupIds.value);
  const selectedGroups = (userGroups ?? []).filter((group) =>
    selectedIds.has(group.id)
  );
  const options = (userGroups ?? [])
    .filter((group) => !selectedIds.has(group.id))
    .map((group) => ({
      value: String(group.id),
      title: group.name,
      description: t("memberCount", { count: group.users.length }),
    }));

  function addGroup(value: string) {
    const id = Number(value);
    if (!Number.isInteger(id) || selectedIds.has(id)) return;
    void groupIdsHelpers.setValue([...groupIds.value, id]);
  }

  function removeGroup(id: number) {
    void groupIdsHelpers.setValue(
      groupIds.value.filter((groupId) => groupId !== id)
    );
  }

  return (
    <div className="flex w-full flex-col gap-3">
      <InputHorizontal
        title={t("toggle.title")}
        description={t("toggle.description")}
        withLabel
      >
        <InputSwitch
          checked={restrict.value}
          onCheckedChange={(checked) => void restrictHelpers.setValue(checked)}
        />
      </InputHorizontal>

      {restrict.value && (
        <>
          <InputSingleComboBox
            value=""
            onValueChange={addGroup}
            options={options}
            placeholder={t("picker.placeholder")}
          />

          {selectedGroups.length === 0 ? (
            <EmptyMessageCard
              sizePreset="main-ui"
              icon={SvgUsers}
              title={t("empty.title")}
              description={t("empty.description")}
            />
          ) : (
            <div className="grid max-h-80 grid-cols-1 gap-2 overflow-y-auto sm:grid-cols-2">
              {selectedGroups.map((group) => (
                <Card key={group.id} color="background-tint-01" padding={2}>
                  <ContentAction
                    icon={SvgUsers}
                    title={group.name}
                    description={t("memberCount", {
                      count: group.users.length,
                    })}
                    sizePreset="main-content"
                    variant="section"
                    rightChildren={
                      <Button
                        icon={SvgX}
                        prominence="tertiary"
                        tooltip={t("remove.tooltip", { name: group.name })}
                        onClick={() => removeGroup(group.id)}
                      />
                    }
                  />
                </Card>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
