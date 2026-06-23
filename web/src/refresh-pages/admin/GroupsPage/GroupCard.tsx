"use client";

import type { Route } from "next";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import type { UserGroup } from "@/lib/types";
import { SvgChevronRight, SvgUserManage, SvgUsers } from "@opal/icons";
import { ContentAction } from "@opal/layouts";
import { Section } from "@/layouts/general-layouts";
import Card from "@/refresh-components/cards/Card";
import { Button } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import {
  isBuiltInGroup,
  buildGroupDescription,
  formatMemberCount,
} from "./utils";
import { renameGroup } from "./svc";
import { toast } from "@/hooks/useToast";
import { useSWRConfig } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";

interface GroupCardProps {
  group: UserGroup;
}

function GroupCard({ group }: GroupCardProps) {
  const { t } = useTranslation();
  const router = useRouter();
  const { mutate } = useSWRConfig();
  const builtIn = isBuiltInGroup(group);
  const isAdmin = group.name === "Admin";
  const isBasic = group.name === "Basic";
  const isSyncing = !group.is_up_to_date;

  async function handleRename(newName: string) {
    try {
      await renameGroup(group.id, newName);
      mutate(SWR_KEYS.adminUserGroups);
      toast.success(t("admin.groups.rename_success", { name: newName }));
    } catch (e) {
      console.error("Failed to rename group:", e);
      toast.error(
        e instanceof Error ? e.message : t("admin.groups.rename_failed")
      );
    }
  }

  return (
    <Card padding={0.5} data-card>
      <ContentAction
        icon={isAdmin ? SvgUserManage : SvgUsers}
        title={group.name}
        description={buildGroupDescription(group)}
        sizePreset="main-content"
        variant="section"
        tag={isBasic ? { title: t("admin.groups.default_tag") } : undefined}
        editable={!builtIn && !isSyncing}
        onTitleChange={!builtIn && !isSyncing ? handleRename : undefined}
        rightChildren={
          <Section flexDirection="row" alignItems="start" gap={0}>
            <div className="py-1">
              <Text mainUiBody text03>
                {formatMemberCount(
                  group.users.filter((u) => u.is_active).length
                )}
              </Text>
            </div>
            <Button
              icon={SvgChevronRight}
              prominence="tertiary"
              tooltip={t("admin.groups.view_group")}
              aria-label={t("admin.groups.view_group")}
              onClick={() => router.push(`/admin/groups/${group.id}` as Route)}
            />
          </Section>
        }
      />
    </Card>
  );
}

export default GroupCard;
