"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import {
  Card,
  IconContainer,
  InputSingleSelect,
  Text,
  type SelectOption,
} from "@opal/components";
import { Section } from "@opal/layouts";
import { SvgUser, SvgUsers } from "@opal/icons";
import type {
  CardPath,
  GroupSpendingLimits,
  SpendingLimitCard,
} from "@/lib/spendingLimits/types";
import LimitCard from "@/views/admin/SpendingLimitsPage/LimitCard";

export enum GroupCardKind {
  POOL = "pool",
  PER_MEMBER = "perMember",
}

const KIND_PATH = {
  [GroupCardKind.POOL]: "pool",
  [GroupCardKind.PER_MEMBER]: "per-member",
} as const satisfies Record<GroupCardKind, string>;
const KIND_ICON = {
  [GroupCardKind.POOL]: SvgUsers,
  [GroupCardKind.PER_MEMBER]: SvgUser,
};
const EMPTY_CARD: SpendingLimitCard = { enabled: true, limits: [] };

function groupCardPath(groupId: number, kind: GroupCardKind): CardPath {
  return `groups/${groupId}/${KIND_PATH[kind]}`;
}

interface GroupFieldProps {
  name: string;
  memberCount: number;
}

/** The group a saved card applies to; it can't change after creation. */
function GroupField({ name, memberCount }: GroupFieldProps) {
  const t = useTranslations("admin.spendingLimits.groups");
  return (
    <Card padding={2} rounding={2} border="solid">
      <Section flexDirection="row" justifyContent="start" gap={1} height="auto">
        <IconContainer icon={SvgUsers} />
        <Section
          flexDirection="row"
          justifyContent="start"
          gap={1}
          width="fit"
          height="auto"
        >
          <Text font="main-ui-body" color="text-04">
            {name}
          </Text>
          <Text font="main-ui-muted" color="text-03">
            {t("field.members", { count: memberCount })}
          </Text>
        </Section>
      </Section>
    </Card>
  );
}

interface GroupLimitCardProps {
  kind: GroupCardKind;
  groupId: number;
  /** null where the card sits on the group's own page. */
  group: { name: string; memberCount: number } | null;
  card: SpendingLimitCard;
  modelOptions: SelectOption[];
  canEdit: boolean;
  onSaved: () => void;
}

export function GroupLimitCard({
  kind,
  groupId,
  group,
  card,
  modelOptions,
  canEdit,
  onSaved,
}: GroupLimitCardProps) {
  const t = useTranslations("admin.spendingLimits.groups");
  return (
    <LimitCard
      title={t(`${kind}.title`)}
      description={t(`${kind}.description`)}
      icon={KIND_ICON[kind]}
      emptyTitle={t(`${kind}.empty`)}
      emptyDescription={t(`${kind}.emptyDescription`)}
      targetLabel={
        group ? t(`${kind}.target`, { group: group.name }) : t(`${kind}.title`)
      }
      card={card}
      path={groupCardPath(groupId, kind)}
      showUsage={kind === GroupCardKind.POOL}
      modelOptions={modelOptions}
      canEdit={canEdit}
      readOnlyNote={
        kind === GroupCardKind.PER_MEMBER ? t("perMember.adminOnly") : undefined
      }
      targetField={
        group ? (
          <GroupField name={group.name} memberCount={group.memberCount} />
        ) : undefined
      }
      onSaved={onSaved}
    />
  );
}

export interface PickableGroup {
  id: number;
  name: string;
  memberCount: number;
}

interface NewGroupLimitCardProps {
  groups: PickableGroup[];
  limited: GroupSpendingLimits[];
  modelOptions: SelectOption[];
  onCancel: () => void;
  onSaved: () => void;
}

/** A card for a group and limit type that have no limits yet. */
export function NewGroupLimitCard({
  groups,
  limited,
  modelOptions,
  onCancel,
  onSaved,
}: NewGroupLimitCardProps) {
  const t = useTranslations("admin.spendingLimits.groups");
  const [groupId, setGroupId] = useState<number | null>(null);
  const [kind, setKind] = useState(GroupCardKind.POOL);

  function isSet(id: number, forKind: GroupCardKind): boolean {
    const cards = limited.find((group) => group.user_group_id === id);
    if (!cards) return false;
    const card = forKind === GroupCardKind.POOL ? cards.pool : cards.per_member;
    return card.limits.length > 0;
  }

  const groupOptions: SelectOption[] = groups.map((group) => ({
    value: String(group.id),
    title: group.name,
    description: t("members", { count: group.memberCount }),
    icon: SvgUsers,
    suffix: isSet(group.id, kind) ? t("picker.limitSet") : undefined,
    disabled: isSet(group.id, kind),
  }));
  const kindOptions: SelectOption[] = Object.values(GroupCardKind).map(
    (value) => ({
      value,
      title: t(`${value}.title`),
      description: t(`${value}.description`),
      icon: KIND_ICON[value],
    })
  );
  const ready = groupId !== null && !isSet(groupId, kind);

  return (
    <LimitCard
      title={t(`${kind}.title`)}
      description={t(`${kind}.description`)}
      icon={KIND_ICON[kind]}
      emptyTitle={t(`${kind}.empty`)}
      emptyDescription={t(`${kind}.emptyDescription`)}
      targetLabel=""
      card={EMPTY_CARD}
      path={ready ? groupCardPath(groupId, kind) : null}
      showUsage={false}
      modelOptions={modelOptions}
      canEdit
      isNew
      targetField={
        <Section flexDirection="row" alignItems="start" gap={1} height="auto">
          <InputSingleSelect
            value={groupId === null ? "" : String(groupId)}
            onValueChange={(value) =>
              setGroupId(value === "" ? null : Number(value))
            }
            placeholder={t("picker.placeholder")}
            options={groupOptions}
            search
          />
          <InputSingleSelect
            value={kind}
            onValueChange={(value) => {
              const picked = Object.values(GroupCardKind).find(
                (option) => option === value
              );
              if (picked) setKind(picked);
            }}
            defaultOption={GroupCardKind.POOL}
            placeholder={t("kind.placeholder")}
            options={kindOptions}
          />
        </Section>
      }
      onCancelNew={onCancel}
      onSaved={onSaved}
    />
  );
}
