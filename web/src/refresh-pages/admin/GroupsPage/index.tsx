"use client";

import type { Route } from "next";
import { useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { SvgExternalLink, SvgUsers, SvgSimpleLoader } from "@opal/icons";
import { Button, MessageCard } from "@opal/components";
import { SettingsLayouts } from "@opal/layouts";
import { errorHandlingFetcher } from "@/lib/fetcher";
import type { UserGroup } from "@/lib/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import GroupsList from "./GroupsList";
import AdminListHeader from "@/sections/admin/AdminListHeader";
import { IllustrationContent } from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";

function GroupsPage() {
  const router = useRouter();
  const [searchQuery, setSearchQuery] = useState("");

  const {
    data: groups,
    error,
    isLoading,
  } = useSWR<UserGroup[]>(SWR_KEYS.adminUserGroups, errorHandlingFetcher);

  return (
    <SettingsLayouts.Root>
      <div data-testid="groups-page-heading">
        <SettingsLayouts.Header icon={SvgUsers} title="用户组" divider>
          <MessageCard
            variant="info"
            title="权限体系即将更新"
            description="Glomi AI 正在过渡到基于用户组的权限体系，可通过每个用户组的权限配置实现更灵活的访问控制。建议你检查用户组结构，为这次更新做好准备。"
            rightChildren={
              <Button
                icon={SvgExternalLink}
                onClick={() =>
                  window.open(
                    "https://docs.glomi.ai/admins/permissions/whats_changing",
                    "_blank",
                    "noopener,noreferrer"
                  )
                }
              >
                了解更多
              </Button>
            }
          />
        </SettingsLayouts.Header>
      </div>

      <SettingsLayouts.Body>
        <AdminListHeader
          hasItems={!isLoading && !error && (groups?.length ?? 0) > 0}
          searchQuery={searchQuery}
          onSearchQueryChange={setSearchQuery}
          placeholder="搜索用户组..."
          emptyStateText="创建用户组以组织用户并管理访问权限。"
          onAction={() => router.push("/admin/groups/create" as Route)}
          actionLabel="新建用户组"
        />

        {isLoading && <SvgSimpleLoader />}

        {error && (
          <IllustrationContent
            illustration={SvgNoResult}
            title="用户组加载失败"
            description="请查看控制台了解更多详情。"
          />
        )}

        {!isLoading && !error && groups && (
          <GroupsList groups={groups} searchQuery={searchQuery} />
        )}
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}

export default GroupsPage;
