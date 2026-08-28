"use client";

import type { Route } from "next";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import type { UserGroup } from "@/lib/types";
import { SvgChevronRight, SvgUserManage, SvgUsers } from "@opal/icons";
import { ContentAction, toast } from "@opal/layouts";
import { Section } from "@/layouts/general-layouts";
import { Button, Card } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import {
  isBuiltInGroup,
  buildGroupDescription,
  formatMemberCount,
} from "./utils";
import { refreshGroupLists, renameGroup } from "./svc";
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

  return (
    <Card border="solid" padding={2} data-card rounding={4}>
      <Section alignItems="start" height="fit">
        <ContentAction
          icon={isAdmin ? SvgUserManage : SvgUsers}
          title={group.name}
          description={buildGroupDescription(group)}
          sizePreset="main-content"
          variant="section"
          tag={builtIn ? { title: t("card.defaultTag.label") } : undefined}
          editable={!isSyncing && canManage}
          onTitleChange={!isSyncing && canManage ? handleRename : undefined}
          rightChildren={
            <Section flexDirection="row" alignItems="start" gap={0}>
              <div className="py-1">
                <Text mainUiBody text03>
                  {formatMemberCount(
                    group.users.filter((u) => u.is_active).length
                  )}
                </Text>
              </div>
              {canManageMembers && (
                <Button
                  icon={SvgChevronRight}
                  prominence="tertiary"
                  tooltip={t("card.viewGroup.label")}
                  aria-label={t("card.viewGroup.label")}
                  onClick={() =>
                    router.push(`/admin/groups/${group.id}` as Route)
                  }
                />
              )}
            </Section>
          }
        />
      </Section>
    </Card>
  );
}

export default GroupCard;
