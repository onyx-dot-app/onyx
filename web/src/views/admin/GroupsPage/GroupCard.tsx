"use client";

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import type { UserGroup } from "@/lib/types";
import { SvgChevronRight, SvgUser, SvgUserManage, SvgUsers } from "@opal/icons";
import { ContentAction, toast } from "@opal/layouts";
import { Button, SelectCard } from "@opal/components";
import {
  isBuiltInGroup,
  buildGroupDescription,
  displayGroupName,
  formatMemberCount,
} from "@/views/admin/GroupsPage/utils";
import { refreshGroupLists, renameGroup } from "@/views/admin/GroupsPage/svc";
import { useSWRConfig } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { can } from "@/lib/permissions/resource-actions";

interface GroupCardProps {
  group: UserGroup;
}

function GroupCard({ group }: GroupCardProps) {
  const t = useTranslations("admin.groups");
  const router = useRouter();
  const { mutate } = useSWRConfig();
  const builtIn = isBuiltInGroup(group);
  const isAdmin = group.name === "Admin";
  const isBasic = builtIn && group.name === "Basic";
  const isSyncing = !group.is_up_to_date;
  // a default group has only members, so no `manage` — `manage_members` still opens it
  const canManage = can(group, "manage");
  const canManageMembers = can(group, "manage_members");

  async function handleRename(newName: string) {
    try {
      await renameGroup(group.id, newName);
      await refreshGroupLists(mutate);
      toast.success(t("card.toasts.renamed", { name: newName }));
    } catch (e) {
      console.error("Failed to rename group:", e);
      toast.error(
        e instanceof Error ? e.message : t("card.toasts.renameFailed")
      );
    }
  }

  function openGroup() {
    router.push(`/admin/groups/${group.id}`);
  }

  return (
    <SelectCard
      state="filled"
      border="solid"
      padding={2}
      data-card
      rounding={4}
      onClick={canManageMembers ? openGroup : undefined}
    >
      <ContentAction
        icon={isAdmin ? SvgUserManage : isBasic ? SvgUser : SvgUsers}
        title={displayGroupName(group, t)}
        description={buildGroupDescription(group, t)}
        sizePreset="main-content"
        variant="section"
        padding={1}
        suffix={isBasic ? t("card.defaultSuffix.label") : undefined}
        editable={!isSyncing && canManage}
        onTitleChange={!isSyncing && canManage ? handleRename : undefined}
        rightChildren={
          <Button
            rightIcon={SvgChevronRight}
            prominence="tertiary"
            tooltip={t("card.viewGroup.label")}
            disabled={!canManageMembers}
            // Repeats the card's action: a click bubbles to the card's
            // `openGroup`, and the card is the tab stop.
            tabIndex={-1}
          >
            {formatMemberCount(
              group.users.filter((u) => u.is_active).length,
              t
            )}
          </Button>
        }
      />
    </SelectCard>
  );
}

export default GroupCard;
