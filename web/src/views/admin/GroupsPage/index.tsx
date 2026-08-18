"use client";

import type { Route } from "next";
import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { SvgExternalLink, SvgUsers, SvgSimpleLoader } from "@opal/icons";
import { Button, MessageCard } from "@opal/components";
import { SettingsLayouts } from "@opal/layouts";
import { errorHandlingFetcher } from "@/lib/fetcher";
import type { UserGroup } from "@/lib/types";
import { Permission } from "@/lib/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import { useUser } from "@/providers/UserProvider";
import { hasPermission } from "@/lib/permissions";
import { can } from "@/lib/permissions/resource-actions";
import GroupsList from "./GroupsList";
import AdminListHeader from "@/sections/admin/AdminListHeader";
import { IllustrationContent } from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";

function GroupsPage() {
  const router = useRouter();
  const [searchQuery, setSearchQuery] = useState("");
  const { user } = useUser();

  // Create is global-only (route has no allow_scope); gate on the global token, not
  // admin_capabilities, which would show it to scoped managers who'd then 403.
  const canCreateGroup = hasPermission(
    user?.effective_permissions ?? [],
    Permission.MANAGE_USER_GROUPS
  );

  const {
    data: groups,
    error,
    isLoading,
  } = useSWR<UserGroup[]>(
    SWR_KEYS.adminUserGroupsWithDefault,
    errorHandlingFetcher
  );

  // The list is READ_USER_GROUPS-scoped (implied by MANAGE_LLMS etc.), so filter to
  // manageable groups — else a read-only holder sees groups with no open action.
  // `manage_members` is the broadest action, and the only one a default group keeps —
  // so this also hides Admin/Basic from non-full-admins.
  const manageableGroups = useMemo(
    () => (groups ?? []).filter((group) => can(group, "manage_members")),
    [groups]
  );

  return (
    <SettingsLayouts.Root>
      <div data-testid="groups-page-heading">
        <SettingsLayouts.Header icon={SvgUsers} title="Groups" divider>
          <MessageCard
            variant="info"
            title="Permissions have changed"
            description="Onyx now uses group-based permissions. Access is configured per group, so a user's permissions are the combination of every group they belong to."
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
      </div>

      <SettingsLayouts.Body>
        <AdminListHeader
          hasItems={!isLoading && !error && manageableGroups.length > 0}
          searchQuery={searchQuery}
          onSearchQueryChange={setSearchQuery}
          placeholder="Search groups..."
          emptyStateText="Create groups to organize users and manage access."
          onAction={
            canCreateGroup
              ? () => router.push("/admin/groups/create" as Route)
              : undefined
          }
          actionLabel={canCreateGroup ? "New Group" : undefined}
        />

        {isLoading && <SvgSimpleLoader />}

        {error && (
          <IllustrationContent
            illustration={SvgNoResult}
            title="Failed to load groups."
            description="Please check the console for more details."
          />
        )}

        {!isLoading && !error && groups && (
          <GroupsList groups={manageableGroups} searchQuery={searchQuery} />
        )}
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}

export default GroupsPage;
