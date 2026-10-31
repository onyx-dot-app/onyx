"use client";

import { useTranslations } from "next-intl";
import { Button, Card, type SelectOption } from "@opal/components";
import { ContentAction, Section, toast } from "@opal/layouts";
import { SvgTrash, SvgUser, SvgUsers } from "@opal/icons";
import { deleteGroupSpendingLimits } from "@/lib/spendingLimits/svc";
import type { GroupSpendingLimitCards } from "@/lib/spendingLimits/types";
import LimitCardEditor from "@/views/admin/SpendingLimitsPage/LimitCardEditor";

interface GroupLimitsCardProps {
  groupId: number;
  groupName: string;
  memberCount: number;
  cards: GroupSpendingLimitCards;
  modelOptions: SelectOption[];
  /** A group manager may edit the pool of a group they manage. */
  canEditPool: boolean;
  /** Per-member limits can lift a member above the workspace default, so
   *  only a full admin edits them. */
  canEditPerMember: boolean;
  onChanged: () => void;
}

export default function GroupLimitsCard({
  groupId,
  groupName,
  memberCount,
  cards,
  modelOptions,
  canEditPool,
  canEditPerMember,
  onChanged,
}: GroupLimitsCardProps) {
  const t = useTranslations("admin.spendingLimits");

  async function removeAll() {
    try {
      await deleteGroupSpendingLimits(groupId);
      toast.success(t("groups.removed", { group: groupName }));
      onChanged();
    } catch (error) {
      toast.error(
        t("card.saveFailed", {
          error: error instanceof Error ? error.message : String(error),
        })
      );
    }
  }

  return (
    <Card border="solid" rounding={4} padding={3}>
      <Section gap={3} alignItems="stretch" height="auto">
        <ContentAction
          sizePreset="main-ui"
          variant="section"
          icon={SvgUsers}
          title={groupName}
          description={t("groups.members", { count: memberCount })}
          rightChildren={
            canEditPerMember ? (
              <Button
                variant="danger"
                prominence="tertiary"
                icon={SvgTrash}
                size="sm"
                tooltip={t("groups.remove.tooltip")}
                aria-label={t("groups.remove.tooltip")}
                onClick={() => void removeAll()}
              />
            ) : undefined
          }
        />
        <LimitCardEditor
          title={t("groups.pool.title")}
          description={t("groups.pool.description")}
          icon={SvgUsers}
          card={cards.pool}
          path={`groups/${groupId}/pool`}
          showUsage
          modelOptions={modelOptions}
          canEdit={canEditPool}
          onSaved={onChanged}
        />
        <LimitCardEditor
          title={t("groups.perMember.title")}
          description={t("groups.perMember.description")}
          icon={SvgUser}
          card={cards.per_member}
          path={`groups/${groupId}/per-member`}
          showUsage={false}
          modelOptions={modelOptions}
          canEdit={canEditPerMember}
          readOnlyNote={t("groups.perMember.adminOnly")}
          onSaved={onChanged}
        />
      </Section>
    </Card>
  );
}
