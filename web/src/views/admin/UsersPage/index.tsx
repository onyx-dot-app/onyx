"use client";

import { useState } from "react";
import { SvgDevKit, SvgExternalLink, SvgUser, SvgUserPlus } from "@opal/icons";
import { Button, MessageCard } from "@opal/components";
import { SettingsLayouts } from "@opal/layouts";
import { useScimToken } from "@/hooks/useScimToken";
import { useTierAtLeast } from "@/hooks/useTierAtLeast";
import { useSettings } from "@/lib/settings/hooks";
import { Tier } from "@/lib/settings/types";
import useUserCounts from "@/hooks/useUserCounts";
import { UserStatus } from "@/lib/types";
import type { StatusFilter } from "./interfaces";

import UsersSummary from "./UsersSummary";
import UsersTable from "./UsersTable";
import InviteUsersModal from "./InviteUsersModal";
import CraftAccessModal from "./CraftAccessModal";

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
  const [craftAccessOpen, setCraftAccessOpen] = useState(false);
  const settings = useSettings();
  const craftAvailable = settings?.onyx_craft_available === true;

  return (
    <SettingsLayouts.Root width="lg">
      <SettingsLayouts.Header
        title="Users & Requests"
        icon={SvgUser}
        rightChildren={
          <div className="flex items-center gap-2">
            {craftAvailable && (
              <Button
                icon={SvgDevKit}
                prominence="secondary"
                onClick={() => setCraftAccessOpen(true)}
              >
                Craft Access
              </Button>
            )}
            <Button icon={SvgUserPlus} onClick={() => setInviteOpen(true)}>
              Invite Users
            </Button>
          </div>
        }
      >
        <MessageCard
          variant="info"
          title="Upcoming changes to permissions"
          description="Onyx is transitioning to group-based permissions for more granular access control. Curator and Global Curator roles will be replaced by configurable group permissions. We recommend reviewing current role assignments to ensure a smooth transition."
          rightChildren={
            <Button
              icon={SvgExternalLink}
              onClick={() =>
                window.open(
                  "https://docs.onyx.app/admins/permissions/whats_changing",
                  "_blank",
                  "noopener,noreferrer"
                )
              }
            >
              Learn more
            </Button>
          }
        />
      </SettingsLayouts.Header>
      <SettingsLayouts.Body>
        <UsersContent />
      </SettingsLayouts.Body>

      <InviteUsersModal open={inviteOpen} onOpenChange={setInviteOpen} />
      {craftAvailable && (
        <CraftAccessModal
          open={craftAccessOpen}
          onOpenChange={setCraftAccessOpen}
        />
      )}
    </SettingsLayouts.Root>
  );
}
