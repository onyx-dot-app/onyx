"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { SvgUser, SvgUserPlus } from "@opal/icons";
import { Button } from "@opal/components";
import { SettingsLayouts } from "@opal/layouts";
import { useScimToken } from "@/hooks/useScimToken";
import { useTierAtLeast } from "@/lib/tiers/hooks";
import { Tier } from "@/lib/tiers/types";
import useUserCounts from "@/hooks/useUserCounts";
import { UserStatus } from "@/lib/types";
import type { StatusFilter } from "./types";

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

  const {
    activeCount,
    invitedCount,
    pendingCount,
    accountTypeCounts,
    statusCounts,
  } = useUserCounts();

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
        accountTypeCounts={accountTypeCounts}
        statusCounts={statusCounts}
      />
    </>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function UsersPage() {
  const t = useTranslations("admin.users");
  const [inviteOpen, setInviteOpen] = useState(false);

  return (
    <SettingsLayouts.Root width="lg">
      <SettingsLayouts.Header
        title={t("page.title")}
        icon={SvgUser}
        actions={[
          <Button
            key="primary"
            icon={SvgUserPlus}
            onClick={() => setInviteOpen(true)}
          >
            {t("page.inviteButton.label")}
          </Button>,
        ]}
      />
      <SettingsLayouts.Body>
        <UsersContent />
      </SettingsLayouts.Body>

      <InviteUsersModal open={inviteOpen} onOpenChange={setInviteOpen} />
    </SettingsLayouts.Root>
  );
}
