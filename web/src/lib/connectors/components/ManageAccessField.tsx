"use client";

import { useTranslations } from "next-intl";
import { Card, Divider, MessageCard, Text } from "@opal/components";
import { Content, ContentAction, Section } from "@opal/layouts";
import { SvgUserManage } from "@opal/icons";
import useUsers from "@/hooks/useUsers";
import { Permission } from "@/lib/types";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import GroupShareList from "@/lib/connectors/components/GroupShareList";

interface ManageAccessFieldProps {
  disabled?: boolean;
}

/**
 * Who can operate or edit the connector: admins always, plus the groups added
 * here (sent as `groups`, so each is an Editor).
 */
export default function ManageAccessField({
  disabled,
}: ManageAccessFieldProps) {
  const t = useTranslations("admin.connectorsList.settings.manageAccess");
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

  const adminsRow = (
    <Card color="background-tint-01" border="none" padding={2}>
      <ContentAction
        icon={SvgUserManage}
        title={t("admins.title")}
        description={
          adminCount === undefined
            ? undefined
            : tRestriction("memberCount", { count: adminCount })
        }
        sizePreset="main-ui"
        variant="section"
        padding={0}
        rightChildren={
          <Text font="secondary-body" color="text-03">
            {t("admins.alwaysShared")}
          </Text>
        }
      />
    </Card>
  );

  return (
    <Section gap={3} alignItems="stretch" height="fit">
      <Content
        title={t("title")}
        description={t("description")}
        sizePreset="main-ui"
        variant="section"
      />
      <GroupShareList
        name="groups"
        placeholder={t("placeholder")}
        leadingRow={adminsRow}
        disabled={disabled}
      />
      <Divider paddingParallel={0} paddingPerpendicular={0} />
      <MessageCard variant="info" title={t("note")} />
    </Section>
  );
}
