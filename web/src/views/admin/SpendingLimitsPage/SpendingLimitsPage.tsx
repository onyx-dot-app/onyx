"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  InputSingleComboBox,
  Text,
  type SelectOption,
} from "@opal/components";
import { ContentAction, Section, SettingsLayouts } from "@opal/layouts";
import { PageLoader } from "@opal/loaders";
import { SvgOrganization, SvgPlusCircle, SvgUser } from "@opal/icons";
import useGroups from "@/hooks/useGroups";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { useAdminRouteTitle } from "@/lib/adminNavLabels";
import { useModelOptions, useSpendingLimits } from "@/lib/spendingLimits/hooks";
import type { SpendingLimitCard } from "@/lib/spendingLimits/types";
import GroupLimitsCard from "@/views/admin/SpendingLimitsPage/GroupLimitsCard";
import LimitCardEditor from "@/views/admin/SpendingLimitsPage/LimitCardEditor";
import { withCardModels } from "@/views/admin/SpendingLimitsPage/modelOptions";

const route = ADMIN_ROUTES.SPENDING_LIMITS;
const EMPTY_CARD: SpendingLimitCard = { enabled: true, limits: [] };

export default function SpendingLimitsPage() {
  const t = useTranslations("admin.spendingLimits");
  const adminRouteTitle = useAdminRouteTitle();
  const { data, error, mutate } = useSpendingLimits();
  const { data: groups } = useGroups();
  const baseModelOptions = useModelOptions();
  // Groups picked through "Add Group Limit" that have no saved limit yet.
  const [newGroupIds, setNewGroupIds] = useState<number[]>([]);
  const [pickingGroup, setPickingGroup] = useState(false);

  const header = (
    <SettingsLayouts.Header
      icon={route.icon}
      title={adminRouteTitle(route)}
      description={t("page.description")}
      divider
    />
  );

  if (error) {
    return (
      <SettingsLayouts.Root width="lg">
        {header}
        <SettingsLayouts.Body>
          <Text color="status-error-05">{t("page.loadFailed")}</Text>
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    );
  }
  if (!data) {
    return (
      <SettingsLayouts.Root width="lg">
        {header}
        <SettingsLayouts.Body>
          <PageLoader />
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    );
  }

  const modelOptions = withCardModels(baseModelOptions, [
    data.workspace_pool,
    data.workspace_per_user,
    ...data.groups.flatMap((group) => [group.pool, group.per_member]),
  ]);
  const limitedGroupIds = new Set(
    data.groups.map((group) => group.user_group_id)
  );
  const pendingGroups = (groups ?? []).filter(
    (group) => newGroupIds.includes(group.id) && !limitedGroupIds.has(group.id)
  );
  const pickableGroups: SelectOption[] = (groups ?? [])
    .filter(
      (group) =>
        !limitedGroupIds.has(group.id) && !newGroupIds.includes(group.id)
    )
    .map((group) => ({
      value: String(group.id),
      title: group.name,
      description: t("groups.members", { count: group.users.length }),
    }));

  function refresh() {
    void mutate();
  }

  return (
    <SettingsLayouts.Root width="lg">
      {header}
      <SettingsLayouts.Body>
        <Section gap={3} alignItems="stretch" height="auto">
          <ContentAction
            sizePreset="main-content"
            variant="section"
            title={t("workspace.title")}
            description={t("workspace.description")}
          />
          <LimitCardEditor
            title={t("workspace.pool.title")}
            description={t("workspace.pool.description")}
            icon={SvgOrganization}
            card={data.workspace_pool}
            path="workspace/pool"
            showUsage
            modelOptions={modelOptions}
            canEdit
            onSaved={refresh}
          />
          <LimitCardEditor
            title={t("workspace.perUser.title")}
            description={t("workspace.perUser.description")}
            icon={SvgUser}
            card={data.workspace_per_user}
            path="workspace/per-user"
            showUsage={false}
            modelOptions={modelOptions}
            canEdit
            onSaved={refresh}
          />
        </Section>

        <Section gap={3} alignItems="stretch" height="auto">
          <ContentAction
            sizePreset="main-content"
            variant="section"
            title={t("groups.title")}
            description={t("groups.description")}
            rightChildren={
              <Button
                icon={SvgPlusCircle}
                disabled={pickableGroups.length === 0}
                onClick={() => setPickingGroup(true)}
              >
                {t("groups.add.label")}
              </Button>
            }
          />
          {pickingGroup && (
            <InputSingleComboBox
              value=""
              onValueChange={(value) => {
                if (value === "") return;
                setNewGroupIds((prev) => [...prev, Number(value)]);
                setPickingGroup(false);
              }}
              placeholder={t("groups.picker.placeholder")}
              options={pickableGroups}
            />
          )}
          {data.groups.length === 0 && pendingGroups.length === 0 && (
            <Text font="secondary-body" color="text-03">
              {t("groups.empty")}
            </Text>
          )}
          {data.groups.map((group) => (
            <GroupLimitsCard
              key={group.user_group_id}
              groupId={group.user_group_id}
              groupName={group.group_name}
              memberCount={group.member_count}
              cards={group}
              modelOptions={modelOptions}
              canEditPool
              canEditPerMember
              onChanged={refresh}
            />
          ))}
          {pendingGroups.map((group) => (
            <GroupLimitsCard
              key={group.id}
              groupId={group.id}
              groupName={group.name}
              memberCount={group.users.length}
              cards={{ pool: EMPTY_CARD, per_member: EMPTY_CARD }}
              modelOptions={modelOptions}
              canEditPool
              canEditPerMember
              onChanged={refresh}
            />
          ))}
        </Section>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
