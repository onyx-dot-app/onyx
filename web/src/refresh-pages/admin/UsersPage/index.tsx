"use client";

import { useState } from "react";
import { SvgExternalLink, SvgUser, SvgUserPlus } from "@opal/icons";
import { Button } from "@opal/components";
import Message from "@/refresh-components/messages/Message";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { useScimToken } from "@/hooks/useScimToken";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
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
  const isEe = usePaidEnterpriseFeaturesEnabled();

  const { data: scimToken } = useScimToken();
  const showScim = isEe && !!scimToken;

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
        title="Users & Requests"
        icon={SvgUser}
        rightChildren={
          <Button icon={SvgUserPlus} onClick={() => setInviteOpen(true)}>
            Invite Users
          </Button>
        }
      >
        <Message
          info
          static
          large
          close={false}
          icon
          text="Upcoming changes to permissions"
          description="Onyx is transitioning to group-based permissions for more granular access control. Curator and Global Curator roles will be replaced by configurable group permissions. We recommend reviewing current role assignments to ensure a smooth transition."
          actions="Learn more"
          actionIcon={SvgExternalLink}
          onAction={() =>
            window.open(
              "https://docs.onyx.app/admins/permissions/whats_changing",
              "_blank",
              "noopener,noreferrer"
            )
          }
          className="w-full"
        />
      </SettingsLayouts.Header>
      <SettingsLayouts.Body>
        <UsersContent />
      </SettingsLayouts.Body>

      <InviteUsersModal open={inviteOpen} onOpenChange={setInviteOpen} />
    </SettingsLayouts.Root>
  );
}
