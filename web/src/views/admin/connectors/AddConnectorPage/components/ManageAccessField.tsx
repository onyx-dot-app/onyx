"use client";

import { useField } from "formik";
import { useTranslations } from "next-intl";
import { Divider, MessageCard, Tooltip } from "@opal/components";
import { usePlans, useTierAtLeast } from "@/lib/tiers/hooks";
import { Tier } from "@/lib/tiers/types";
import { Content, Section } from "@opal/layouts";
import { SvgBarChart, SvgEditBig, SvgUserManage } from "@opal/icons";
import useUsers from "@/hooks/useUsers";
import { Permission } from "@/lib/types";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import type { ConnectorManageRole } from "@/lib/connectors/accessType";
import GroupShareList, {
  type GroupShareGroup,
  type GroupShareLockedRow,
} from "@/lib/connectors/components/GroupShareList";
import {
  SharePermissionMenu,
  type SharePermissionMenuOption,
} from "@/lib/permissions/components";

interface ManageAccessFieldProps {
  disabled?: boolean;
}

/**
 * Who can operate or edit the connector: admins always, plus the groups added
 * here (sent as `groups`, so each is an Editor). Groups need the Business
 * tier: below it the field still shows, with the picker locked and the
 * Business plan tag.
 */
export default function ManageAccessField({
  disabled,
}: ManageAccessFieldProps) {
  const t = useTranslations("admin.connectorsList.settings.manageAccess");
  const plans = usePlans();
  const businessTier = useTierAtLeast(Tier.BUSINESS);
  const groupsLocked: boolean = disabled === true || !businessTier;
  const tRestriction = useTranslations("admin.connector.groupRestriction");
  const { isScopedManager } = usePermissionAuthority(
    Permission.MANAGE_CONNECTORS
  );
  const { data: usersData } = useUsers({ includeApiKeys: false });
  // A scoped manager's user list stops at their groups, so it would count
  // too few admins; leave the count out rather than show a wrong one.
  const adminCount = isScopedManager
    ? undefined
    : usersData?.accepted.filter((user) => user.is_admin).length;

  const [roles, , rolesHelpers] =
    useField<Record<string, ConnectorManageRole>>("group_roles");
  const roleOptions: SharePermissionMenuOption<ConnectorManageRole>[] = [
    {
      value: "editor",
      label: t("role.editor.label"),
      description: t("role.editor.description"),
      icon: SvgEditBig,
    },
    {
      value: "operator",
      label: t("role.operator.label"),
      description: t("role.operator.description"),
      icon: SvgBarChart,
    },
  ];

  function setRole(groupId: number, role: ConnectorManageRole | undefined) {
    const { [String(groupId)]: _dropped, ...rest } = roles.value;
    void rolesHelpers.setValue(
      role === undefined ? rest : { ...rest, [String(groupId)]: role }
    );
  }

  // A group without a role is an Editor, which is what it is sent as.
  function renderRoleMenu(group: GroupShareGroup, remove: () => void) {
    return (
      <SharePermissionMenu
        value={roles.value[String(group.id)] ?? "editor"}
        options={roleOptions}
        onChange={(role) => setRole(group.id, role)}
        onRemove={() => {
          setRole(group.id, undefined);
          remove();
        }}
        removeLabel={t("role.removeAccess.label")}
        menuWidth={60}
        ariaLabel={t("role.menu.ariaLabel", { name: group.name })}
        disabled={groupsLocked}
      />
    );
  }

  const adminsRow: GroupShareLockedRow = {
    id: "admins",
    name: t("admins.title"),
    icon: SvgUserManage,
    memberCount: adminCount,
    note: t("admins.alwaysShared"),
  };

  return (
    <Section gap={3} alignItems="stretch" height="fit">
      <Content
        title={t("title")}
        description={t("description")}
        tag={businessTier ? undefined : plans[Tier.BUSINESS].tag}
        sizePreset="main-ui"
        variant="section"
      />
      {/* The list is tall, so the tooltip stays level with the pointer. */}
      <Tooltip
        tooltip={businessTier ? undefined : plans[Tier.BUSINESS].tooltip}
        align="follow"
      >
        <div className="w-full">
          <GroupShareList
            name="groups"
            label={t("title")}
            placeholder={t("placeholder")}
            lockedRows={[adminsRow]}
            rowAction={renderRoleMenu}
            disabled={groupsLocked}
          />
        </div>
      </Tooltip>
      <Divider paddingParallel={0} paddingPerpendicular={0} />
      <MessageCard
        variant="default"
        title={t("note")}
        outerPadding={1}
        innerPadding={1}
        rounding={3}
      />
    </Section>
  );
}
