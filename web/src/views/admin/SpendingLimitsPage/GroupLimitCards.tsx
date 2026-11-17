"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { InputSingleSelect, type SelectOption } from "@opal/components";
import { Section } from "@opal/layouts";
import { SvgUser, SvgUsers } from "@opal/icons";
import { richNodes } from "@opal/utils";
import type {
  CardPath,
  GroupSpendingLimits,
  SpendingLimitCard,
} from "@/lib/spendingLimits/types";
import LimitCard from "@/views/admin/SpendingLimitsPage/LimitCard";
import {
  EMPHASIS,
  cardSummaryLimits,
  useLimitSummary,
} from "@/views/admin/SpendingLimitsPage/summary";

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

interface GroupLimitCardProps {
  kind: GroupCardKind;
  groupId: number;
  /** null where the card sits on the group's own page. */
  group: { name: string; memberCount: number } | null;
  card: SpendingLimitCard;
  modelOptions: SelectOption[];
  canEdit: boolean;
  onSaved: () => void;
  /** Each new value opens the card and scrolls to it. */
  revealKey?: number;
}

export function GroupLimitCard({
  kind,
  groupId,
  group,
  card,
  modelOptions,
  canEdit,
  onSaved,
  revealKey,
}: GroupLimitCardProps) {
  const t = useTranslations("admin.spendingLimits.groups");
  return (
    <LimitCard
      title={group ? group.name : t(`${kind}.title`)}
      description={
        group
          ? t(`${kind}.members`, { count: group.memberCount })
          : t(`${kind}.description`)
      }
      icon={KIND_ICON[kind]}
      emptyTitle={t(`${kind}.empty`)}
      emptyDescription={t(`${kind}.emptyDescription`)}
      targetLabel={t(`${kind}.target`)}
      summaryPrefix={group?.name}
      card={card}
      path={groupCardPath(groupId, kind)}
      showUsage={kind === GroupCardKind.POOL}
      modelOptions={modelOptions}
      canEdit={canEdit}
      readOnlyNote={
        kind === GroupCardKind.PER_MEMBER ? t("perMember.adminOnly") : undefined
      }
      onSaved={onSaved}
      revealKey={revealKey}
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
  /** Called instead of picking a group whose card of this kind exists. */
  onPickLimited: (groupId: number, kind: GroupCardKind) => void;
}

/** A card for a group and limit type that have no limits yet. */
export function NewGroupLimitCard({
  groups,
  limited,
  modelOptions,
  onCancel,
  onSaved,
  onPickLimited,
}: NewGroupLimitCardProps) {
  const t = useTranslations("admin.spendingLimits.groups");
  const summarize = useLimitSummary();
  const [groupId, setGroupId] = useState<number | null>(null);
  const [kind, setKind] = useState(GroupCardKind.POOL);

  function existingCard(
    id: number,
    forKind: GroupCardKind
  ): SpendingLimitCard | null {
    const cards = limited.find((group) => group.user_group_id === id);
    if (!cards) return null;
    const card = forKind === GroupCardKind.POOL ? cards.pool : cards.per_member;
    return card.limits.length > 0 ? card : null;
  }

  function isSet(id: number, forKind: GroupCardKind): boolean {
    return existingCard(id, forKind) !== null;
  }

  function pick(id: number | null, forKind: GroupCardKind) {
    if (id !== null && isSet(id, forKind)) {
      onPickLimited(id, forKind);
      return;
    }
    setGroupId(id);
    setKind(forKind);
  }

  const groupOptions: SelectOption[] = groups.map((group) => {
    const card = existingCard(group.id, kind);
    return {
      value: String(group.id),
      title: group.name,
      description: t("members", { count: group.memberCount }),
      info: card
        ? richNodes(
            <>
              {t("picker.limitSet")}
              <br />
              {summarize(cardSummaryLimits(card), EMPHASIS.secondary)}
            </>
          )
        : undefined,
    };
  });
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
      title={t("new.title")}
      description={t(`new.${kind}.description`)}
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
              pick(value === "" ? null : Number(value), kind)
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
              if (picked) pick(groupId, picked);
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
