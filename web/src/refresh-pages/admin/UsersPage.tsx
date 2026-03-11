"use client";

import { SvgUser, SvgUserPlus } from "@opal/icons";
import { Button } from "@opal/components";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { useScimToken } from "@/hooks/useScimToken";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import useUserCounts from "@/hooks/useUserCounts";

import UsersSummary from "./UsersPage/UsersSummary";

// ---------------------------------------------------------------------------
// Users page content
// ---------------------------------------------------------------------------

function UsersContent() {
  const isEe = usePaidEnterpriseFeaturesEnabled();

  const { data: scimToken } = useScimToken();
  const showScim = isEe && !!scimToken;

  const { activeCount, invitedCount, pendingCount } = useUserCounts();

  return (
    <>
      <UsersSummary
        activeUsers={activeCount}
        pendingInvites={invitedCount}
        requests={pendingCount}
        showScim={showScim}
      />

      {/* Table and filters will be added in subsequent PRs */}
    </>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function UsersPage() {
  return (
    <SettingsLayouts.Root width="lg">
      <SettingsLayouts.Header
        title="Users & Requests"
        icon={SvgUser}
        rightChildren={
          // TODO (ENG-3806): Wire up invite modal
          <Button icon={SvgUserPlus}>Invite Users</Button>
        }
      />
      <SettingsLayouts.Body>
        <UsersContent />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
