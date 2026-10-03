"use client";

import { useTranslations } from "next-intl";
import { Card, Divider, MessageCard, Text } from "@opal/components";
import { Content, ContentAction, Section } from "@opal/layouts";
import { SvgUserManage } from "@opal/icons";
import useUsers from "@/hooks/useUsers";
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
  const { data: usersData } = useUsers({ includeApiKeys: false });
  const adminCount = usersData?.accepted.filter((user) => user.is_admin).length;

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
