"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { mutate } from "swr";
import {
  Card,
  Divider,
  InputSingleComboBox,
  OnyxLoader,
  Text,
} from "@opal/components";
import { Content, toast } from "@opal/layouts";
import {
  SvgBarChart,
  SvgEdit,
  SvgInfo,
  SvgUserManage,
  SvgUsers,
} from "@opal/icons";
import useGroups from "@/hooks/useGroups";
import { useCCPairManageAccess } from "@/lib/connectors/manageAccess/hooks";
import { setCCPairManageAccess } from "@/lib/connectors/manageAccess/svc";
import type {
  CCPairManageAccessRow,
  ConnectorManageRole,
} from "@/lib/connectors/manageAccess/types";
import { buildCCPairInfoUrl } from "@/lib/connectors/utils";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { UserGroup } from "@/lib/types";
import { ShareAccessRow } from "@/sections/modals/ShareAccessRow";
import { StaticPermissionLabel } from "@/sections/modals/ShareModalPermissionControls";
import {
  SharePermissionMenu,
  type SharePermissionMenuOption,
} from "@/sections/modals/SharePermissionMenu";

export interface ConnectorManageAccessCardProps {
  ccPairId: number;
  /** The caller is an Editor of the pair: may change who manages it. */
  canEdit: boolean;
}

/**
 * Which groups manage a connector, as Editor or Operator. Groups with a global
 * Manage Connectors grant show as fixed Editor rows. Each change saves at once.
 */
export function ConnectorManageAccessCard({
  ccPairId,
  canEdit,
}: ConnectorManageAccessCardProps) {
  const t = useTranslations("admin.connectorManageAccess");
  const { data: rows, error } = useCCPairManageAccess(ccPairId, true);
  // Default groups included: the Admin group is a fixed row and needs a count.
  const { data: groups } = useGroups(true);
  const [isSaving, setIsSaving] = useState(false);

  const groupsById = useMemo(
    () =>
      new Map<number, UserGroup>(
        (groups ?? []).map((group) => [group.id, group])
      ),
    [groups]
  );

  const roleOptions: SharePermissionMenuOption<ConnectorManageRole>[] = useMemo(
    () => [
      {
        value: "editor",
        label: t("role.editor.label"),
        description: t("role.editor.description"),
        icon: SvgEdit,
      },
      {
        value: "operator",
        label: t("role.operator.label"),
        description: t("role.operator.description"),
        icon: SvgBarChart,
      },
    ],
    [t]
  );

  const fixedRows = (rows ?? []).filter((row) => row.is_fixed);
  const storedRows = (rows ?? []).filter((row) => !row.is_fixed);
  const shownGroupIds = new Set((rows ?? []).map((row) => row.group_id));

  // Default groups and groups with a global grant cannot be stored.
  const addOptions = (groups ?? [])
    .filter((group) => !group.is_default && !shownGroupIds.has(group.id))
    .map((group) => ({
      value: String(group.id),
      title: group.name,
      description: t("row.managerCount", { count: group.manager_ids.length }),
    }));

  async function save(nextRows: CCPairManageAccessRow[]) {
    setIsSaving(true);
    try {
      const saved = await setCCPairManageAccess(
        ccPairId,
        nextRows.map((row) => ({ group_id: row.group_id, role: row.role })),
        t("toasts.saveFailed")
      );
      await mutate(SWR_KEYS.ccPairManageAccess(ccPairId), saved, {
        revalidate: false,
      });
      // The caller's own role may have changed with the rows.
      void mutate(buildCCPairInfoUrl(ccPairId));
      toast.success(t("toasts.saved"));
    } catch (saveError) {
      toast.error(
        saveError instanceof Error ? saveError.message : t("toasts.saveFailed")
      );
    } finally {
      setIsSaving(false);
    }
  }

  function addGroup(value: string) {
    const group = groupsById.get(Number(value));
    if (!group || shownGroupIds.has(group.id)) return;
    void save([
      ...storedRows,
      {
        group_id: group.id,
        group_name: group.name,
        role: "operator",
        is_fixed: false,
      },
    ]);
  }

  function changeRole(groupId: number, role: ConnectorManageRole) {
    void save(
      storedRows.map((row) =>
        row.group_id === groupId ? { ...row, role } : row
      )
    );
  }

  function removeGroup(groupId: number) {
    void save(storedRows.filter((row) => row.group_id !== groupId));
  }

  function memberCount(groupId: number): string | undefined {
    const group = groupsById.get(groupId);
    return group
      ? t("row.memberCount", { count: group.users.length })
      : undefined;
  }

  function managerCount(groupId: number): string | undefined {
    const group = groupsById.get(groupId);
    return group
      ? t("row.managerCount", { count: group.manager_ids.length })
      : undefined;
  }

  return (
    <Card border="solid" padding={3} rounding={4}>
      <div className="flex flex-col gap-2">
        <div className="px-1 pt-1">
          <Content
            description={t("header.description")}
            sizePreset="main-ui"
            title={t("header.title")}
            variant="section"
          />
        </div>

        {canEdit && (
          <div className="px-1">
            <InputSingleComboBox
              disabled={isSaving}
              onValueChange={addGroup}
              options={addOptions}
              placeholder={t("picker.placeholder")}
              value=""
            />
          </div>
        )}

        {!rows && !error ? (
          <div className="flex justify-center p-2">
            <OnyxLoader size={24} />
          </div>
        ) : error ? (
          <div className="px-2">
            <Text color="text-03" font="secondary-body">
              {t("loadError")}
            </Text>
          </div>
        ) : (
          <div className="flex flex-col gap-1 p-1">
            {fixedRows.map((row) => (
              <ShareAccessRow
                description={memberCount(row.group_id)}
                icon={SvgUserManage}
                key={row.group_id}
                rightChildren={
                  <div className="flex w-full items-center justify-between gap-1 pe-1">
                    <StaticPermissionLabel
                      icon={SvgEdit}
                      label={t("role.editor.label")}
                      muted
                    />
                    <div className="flex shrink-0 items-center gap-1">
                      <Text
                        color="text-03"
                        font="secondary-body"
                        wordWrap="whitespace-nowrap"
                      >
                        {t("row.alwaysShared")}
                      </Text>
                      <SvgUserManage
                        aria-hidden
                        className="stroke-text-03"
                        size={16}
                      />
                    </div>
                  </div>
                }
                title={row.group_name}
                wide
              />
            ))}

            {storedRows.map((row) => (
              <ShareAccessRow
                avatarIcon={SvgUsers}
                description={managerCount(row.group_id)}
                icon={SvgUsers}
                key={row.group_id}
                rightChildren={
                  <SharePermissionMenu
                    ariaLabel={t("row.roleMenu.ariaLabel", {
                      name: row.group_name,
                    })}
                    disabled={!canEdit || isSaving}
                    menuWidth="lg"
                    onChange={(role) => changeRole(row.group_id, role)}
                    onRemove={() => removeGroup(row.group_id)}
                    options={roleOptions}
                    removeLabel={t("row.removeAccess")}
                    value={row.role}
                  />
                }
                title={row.group_name}
                wide
              />
            ))}
          </div>
        )}

        <div className="flex flex-col gap-4 p-1">
          <Divider paddingParallel={0} paddingPerpendicular={0} />
          <Card
            border="solid"
            color="background-tint-01"
            padding={1}
            rounding={3}
          >
            <div className="flex items-start gap-1 p-1">
              <div className="flex h-5 w-5 shrink-0 items-center justify-center">
                <SvgInfo aria-hidden className="stroke-text-03" size={16} />
              </div>
              <div className="px-0.5">
                <Text color="text-03" font="main-ui-muted">
                  {t("footer.note")}
                </Text>
              </div>
            </div>
          </Card>
        </div>
      </div>
    </Card>
  );
}
