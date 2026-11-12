"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Card, Text } from "@opal/components";
import { Content, Section, SettingsLayouts } from "@opal/layouts";
import { PageLoader } from "@opal/loaders";
import { SvgOrganization, SvgPlusCircle, SvgUser } from "@opal/icons";
import useGroups from "@/hooks/useGroups";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { useAdminRouteTitle } from "@/lib/adminNavLabels";
import { useModelOptions, useSpendingLimits } from "@/lib/spendingLimits/hooks";
import {
  GroupCardKind,
  GroupLimitCard,
  NewGroupLimitCard,
} from "@/views/admin/SpendingLimitsPage/GroupLimitCards";
import LimitCard from "@/views/admin/SpendingLimitsPage/LimitCard";
import { withCardModels } from "@/views/admin/SpendingLimitsPage/modelOptions";

const route = ADMIN_ROUTES.SPENDING_LIMITS;

function groupCardKey(groupId: number, kind: GroupCardKind): string {
  return `${groupId}-${kind}`;
}

export default function SpendingLimitsPage() {
  const t = useTranslations("admin.spendingLimits");
  const adminRouteTitle = useAdminRouteTitle();
  const { data, error, mutate } = useSpendingLimits();
  const { data: groups } = useGroups(false, false);
  const baseModelOptions = useModelOptions();
  // Cards opened through "Add Group Limit" that are not saved yet.
  const [newCardKeys, setNewCardKeys] = useState<number[]>([]);
  const [nextNewCardKey, setNextNewCardKey] = useState(0);
  // The group card to open and scroll to, and a count that re-triggers it.
  const [reveal, setReveal] = useState<{ card: string; count: number }>({
    card: "",
    count: 0,
  });

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
      <SettingsLayouts.Root width="sm">
        {header}
        <SettingsLayouts.Body>
          <Text color="status-error-05">{t("page.loadFailed")}</Text>
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    );
  }
  if (!data) {
    return (
      <SettingsLayouts.Root width="sm">
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
  const pickableGroups = (groups ?? []).map((group) => ({
    id: group.id,
    name: group.name,
    memberCount: group.member_count,
  }));

  function refresh() {
    void mutate();
  }

  function addGroupCard() {
    setNewCardKeys((prev) => [...prev, nextNewCardKey]);
    setNextNewCardKey((prev) => prev + 1);
  }

  function dropGroupCard(key: number) {
    setNewCardKeys((prev) => prev.filter((k) => k !== key));
  }

  function revealGroupCard(newCardKey: number, cardKey: string) {
    dropGroupCard(newCardKey);
    setReveal((prev) => ({ card: cardKey, count: prev.count + 1 }));
  }

  const addGroupButton = (
    <Button
      icon={SvgPlusCircle}
      disabled={pickableGroups.length === 0}
      onClick={addGroupCard}
    >
      {t("groups.add.label")}
    </Button>
  );
  const groupCards = data.groups.flatMap((group) =>
    [
      { kind: GroupCardKind.POOL, card: group.pool },
      { kind: GroupCardKind.PER_MEMBER, card: group.per_member },
    ]
      .filter(({ card }) => card.limits.length > 0)
      .map(({ kind, card }) => (
        <GroupLimitCard
          key={groupCardKey(group.user_group_id, kind)}
          kind={kind}
          groupId={group.user_group_id}
          group={{ name: group.group_name, memberCount: group.member_count }}
          card={card}
          modelOptions={modelOptions}
          canEdit
          onSaved={refresh}
          revealKey={
            reveal.card === groupCardKey(group.user_group_id, kind)
              ? reveal.count
              : undefined
          }
        />
      ))
  );
  const noGroupCards = groupCards.length === 0 && newCardKeys.length === 0;

  return (
    <SettingsLayouts.Root width="sm">
      {header}
      <SettingsLayouts.Body>
        <Section gap={3} alignItems="stretch" height="auto">
          <Content
            font="main-content-emphasis"
            title={t("workspace.title")}
            description={t("workspace.description")}
          />
          <Section gap={2} alignItems="stretch" height="auto">
            <LimitCard
              title={t("workspace.pool.title")}
              description={t("workspace.pool.description")}
              icon={SvgOrganization}
              emptyTitle={t("workspace.pool.empty")}
              emptyDescription={t("workspace.pool.emptyDescription")}
              targetLabel={t("workspace.pool.target")}
              card={data.workspace_pool}
              path="workspace/pool"
              showUsage
              modelOptions={modelOptions}
              canEdit
              onSaved={refresh}
            />
            <LimitCard
              title={t("workspace.perUser.title")}
              description={t("workspace.perUser.description")}
              icon={SvgUser}
              emptyTitle={t("workspace.perUser.empty")}
              emptyDescription={t("workspace.perUser.emptyDescription")}
              targetLabel={t("workspace.perUser.target")}
              card={data.workspace_per_user}
              path="workspace/per-user"
              showUsage={false}
              modelOptions={modelOptions}
              canEdit
              onSaved={refresh}
            />
          </Section>
        </Section>

        <Section gap={3} alignItems="stretch" height="auto">
          <Section flexDirection="row" gap={2} height="auto">
            <Content
              font="main-content-emphasis"
              title={t("groups.title")}
              description={t("groups.description")}
            />
            {!noGroupCards && (
              <Section width="fit" height="auto" gap={0}>
                {addGroupButton}
              </Section>
            )}
          </Section>
          {noGroupCards ? (
            <Card padding={4} rounding={4} border="solid">
              <Section flexDirection="row" gap={3} height="auto">
                <Section gap={0} alignItems="start" height="auto">
                  <Text font="main-ui-muted" color="text-03">
                    {t("groups.empty")}
                  </Text>
                </Section>
                <Section gap={0} width="fit" height="auto">
                  {addGroupButton}
                </Section>
              </Section>
            </Card>
          ) : (
            <Section gap={2} alignItems="stretch" height="auto">
              {groupCards}
              {newCardKeys.map((key) => (
                <NewGroupLimitCard
                  key={key}
                  groups={pickableGroups}
                  limited={data.groups}
                  modelOptions={modelOptions}
                  onCancel={() => dropGroupCard(key)}
                  onPickLimited={(groupId, kind) =>
                    revealGroupCard(key, groupCardKey(groupId, kind))
                  }
                  onSaved={() => {
                    dropGroupCard(key);
                    refresh();
                  }}
                />
              ))}
            </Section>
          )}
        </Section>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
