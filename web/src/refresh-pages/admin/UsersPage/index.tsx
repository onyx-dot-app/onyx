"use client";

import { useState } from "react";
import { SvgExternalLink, SvgUser, SvgUserPlus } from "@opal/icons";
import { Button, MessageCard } from "@opal/components";
import { SettingsLayouts } from "@opal/layouts";
import { useScimToken } from "@/hooks/useScimToken";
import { useTierAtLeast } from "@/hooks/useTierAtLeast";
import { Tier } from "@/interfaces/settings";
import useUserCounts from "@/hooks/useUserCounts";
import { UserStatus } from "@/lib/types";
import type { StatusFilter } from "./interfaces";

import UsersSummary from "./UsersSummary";
import UsersTable from "./UsersTable";
import InviteUsersModal from "./InviteUsersModal";

// ---------------------------------------------------------------------------
// Users page content
// ---------------------------------------------------------------------------

function UsersContent() {
  const enterpriseTier = useTierAtLeast(Tier.ENTERPRISE);

  const { data: scimToken } = useScimToken();
  const showScim = enterpriseTier && !!scimToken;

  const { activeCount, invitedCount, pendingCount, roleCounts, statusCounts } =
    useUserCounts();

  const [selectedStatuses, setSelectedStatuses] = useState<StatusFilter>([]);

  const toggleStatus = (target: UserStatus) => {
    setSelectedStatuses((prev) =>
      prev.includes(target)
        ? prev.filter((s) => s !== target)
        : [...prev, target]
    );
  };

  return (
    <>
      <UsersSummary
        activeUsers={activeCount}
        pendingInvites={invitedCount}
        requests={pendingCount}
        showScim={showScim}
        onFilterActive={() => toggleStatus(UserStatus.ACTIVE)}
        onFilterInvites={() => toggleStatus(UserStatus.INVITED)}
        onFilterRequests={() => toggleStatus(UserStatus.REQUESTED)}
      />

      <UsersTable
        selectedStatuses={selectedStatuses}
        onStatusesChange={setSelectedStatuses}
        roleCounts={roleCounts}
        statusCounts={statusCounts}
      />
    </>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function UsersPage() {
  const [inviteOpen, setInviteOpen] = useState(false);

  return (
    <SettingsLayouts.Root width="lg">
      <SettingsLayouts.Header
        title="用户与请求"
        icon={SvgUser}
        rightChildren={
          <Button icon={SvgUserPlus} onClick={() => setInviteOpen(true)}>
            邀请用户
          </Button>
        }
      >
        <MessageCard
          variant="info"
          title="权限即将更新"
          description="Glomi AI 正在过渡到基于用户组的权限体系，以提供更细粒度的访问控制。Curator 和 Global Curator 角色将由可配置的用户组权限替代。建议你检查当前角色分配，确保平滑迁移。"
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
      <SettingsLayouts.Body>
        <UsersContent />
      </SettingsLayouts.Body>

      <InviteUsersModal open={inviteOpen} onOpenChange={setInviteOpen} />
    </SettingsLayouts.Root>
  );
}
