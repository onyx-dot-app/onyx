"use client";

import type { Route } from "next";
import { useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { SvgExternalLink, SvgUsers } from "@opal/icons";
import { Button, MessageCard } from "@opal/components";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
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
        <SettingsLayouts.Header icon={SvgUsers} title="Groups" divider>
          <MessageCard
            variant="info"
            title="Upcoming changes to permissions"
            description="Onyx is transitioning to group-based permissions, enabling more flexible access control through configurable permissions per group. We recommend reviewing your group structure to prepare for this update."
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
          hasItems={!isLoading && !error && (groups?.length ?? 0) > 0}
          searchQuery={searchQuery}
          onSearchQueryChange={setSearchQuery}
          placeholder="Search groups..."
          emptyStateText="Create groups to organize users and manage access."
          onAction={() => router.push("/admin/groups/create" as Route)}
          actionLabel="New Group"
        />

        {isLoading && <SimpleLoader />}

        {error && (
          <IllustrationContent
            illustration={SvgNoResult}
            title="Failed to load groups."
            description="Please check the console for more details."
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
