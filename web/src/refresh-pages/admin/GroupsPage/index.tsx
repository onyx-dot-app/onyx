"use client";

import type { Route } from "next";
import { useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { SvgUsers } from "@opal/icons";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import { errorHandlingFetcher } from "@/lib/fetcher";
import type { UserGroup } from "@/lib/types";
import { USER_GROUP_URL } from "./svc";
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
  } = useSWR<UserGroup[]>(USER_GROUP_URL, errorHandlingFetcher);

  return (
    <SettingsLayouts.Root width="sm">
      {/* This is the sticky header for the groups page. It is used to display
       * the groups page title and search input when scrolling down.
       */}
      <div
        className="sticky top-0 z-settings-header bg-background-tint-01"
        data-testid="groups-page-heading"
      >
        <SettingsLayouts.Header icon={SvgUsers} title="Groups" separator />

        <div className="p-1">
          <AdminListHeader
            hasItems={!isLoading && !error && (groups?.length ?? 0) > 0}
            searchQuery={searchQuery}
            onSearchQueryChange={setSearchQuery}
            placeholder="Search groups..."
            emptyStateText="Create groups to organize users and manage access."
            onAction={() => router.push("/admin/groups/create" as Route)}
            actionLabel="New Group"
          />
        </div>
      </div>

      <SettingsLayouts.Body>
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
