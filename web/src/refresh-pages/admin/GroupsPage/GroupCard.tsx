"use client";

import type { Route } from "next";
import { useRouter } from "next/navigation";
import type { UserGroup } from "@/lib/types";
import { SvgChevronRight, SvgUserManage, SvgUsers } from "@opal/icons";
import { ContentAction } from "@opal/layouts";
import { Section } from "@/layouts/general-layouts";
import Card from "@/refresh-components/cards/Card";
import { Button } from "@opal/components";
// TODO(@raunakab): migrate this `refresh-components/Text` to `@opal/components` Text
import Text from "@/refresh-components/texts/Text";
import {
  isBuiltInGroup,
  buildGroupDescription,
  formatMemberCount,
} from "./utils";
import { renameGroup, USER_GROUP_URL } from "./svc";
import { toast } from "@/hooks/useToast";
import { useSWRConfig } from "swr";

interface GroupCardProps {
  group: UserGroup;
}

function GroupCard({ group }: GroupCardProps) {
  const router = useRouter();
  const { mutate } = useSWRConfig();
  const builtIn = isBuiltInGroup(group);
  const isAdmin = group.name === "Admin";
  const isBasic = group.name === "Basic";
  const isSyncing = !group.is_up_to_date;

  async function handleRename(newName: string) {
    try {
      await renameGroup(group.id, newName);
      mutate(USER_GROUP_URL);
      toast.success(`Group renamed to "${newName}"`);
    } catch (e) {
      console.error("Failed to rename group:", e);
      toast.error(e instanceof Error ? e.message : "Failed to rename group");
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
        tag={isBasic ? { title: "Default" } : undefined}
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
              tooltip="View group"
              aria-label="View group"
              onClick={() => router.push(`/admin/groups/${group.id}` as Route)}
            />
          </Section>
        }
      />
    </Card>
  );
}

export default GroupCard;
