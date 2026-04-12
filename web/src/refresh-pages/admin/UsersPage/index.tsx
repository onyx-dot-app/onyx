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
import { useTranslations } from "next-intl";

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
  const t = useTranslations("admin.users");

  return (
    <SettingsLayouts.Root width="lg">
      <SettingsLayouts.Header
        title={t("title")}
        icon={SvgUser}
        rightChildren={
          <Button icon={SvgUserPlus} onClick={() => setInviteOpen(true)}>
            {t("inviteUsers")}
          </Button>
        }
      >
        <Message
          info
          static
          large
          close={false}
          icon
          text={t("upcomingChangesTitle")}
          description={t("upcomingChangesDesc")}
          actions={t("learnMore")}
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
