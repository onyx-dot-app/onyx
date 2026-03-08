"use client";

import { SvgUser, SvgUserPlus } from "@opal/icons";
import { Button } from "@opal/components";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { useScimToken } from "@/hooks/useScimToken";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import type { InvitedUserSnapshot } from "@/lib/types";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";

import StatsBar from "./UsersPage/StatsBar";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface PaginatedResponse {
  items: unknown[];
  total_items: number;
}

// ---------------------------------------------------------------------------
// Users page content
// ---------------------------------------------------------------------------

function UsersContent() {
  const isEe = usePaidEnterpriseFeaturesEnabled();

  const { data: scimToken } = useScimToken();
  const showScim = isEe && !!scimToken;

  // Active user count — lightweight fetch (page_size=1 to minimize payload)
  const { data: activeData } = useSWR<PaginatedResponse>(
    "/api/manage/users/accepted?page_num=0&page_size=1",
    errorHandlingFetcher
  );

  const { data: invitedUsers } = useSWR<InvitedUserSnapshot[]>(
    "/api/manage/users/invited",
    errorHandlingFetcher
  );

  const { data: pendingUsers } = useSWR<InvitedUserSnapshot[]>(
    NEXT_PUBLIC_CLOUD_ENABLED ? "/api/tenants/users/pending" : null,
    errorHandlingFetcher
  );

  const activeCount = activeData?.total_items ?? null;
  const invitedCount = invitedUsers?.length ?? null;
  const pendingCount = pendingUsers?.length ?? null;

  return (
    <>
      <StatsBar
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
