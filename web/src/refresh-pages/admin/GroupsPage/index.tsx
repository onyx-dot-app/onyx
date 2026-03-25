"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { SvgPlusCircle, SvgUsers } from "@opal/icons";
import { Button } from "@opal/components";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import { errorHandlingFetcher } from "@/lib/fetcher";
import type { UserGroup } from "@/lib/types";
import { USER_GROUP_URL } from "./svc";
import GroupsList from "./GroupsList";
import { Section } from "@/layouts/general-layouts";
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
      <div className="sticky top-0 z-settings-header bg-background-tint-01">
        <SettingsLayouts.Header icon={SvgUsers} title="Groups" separator />

        <Section flexDirection="row" padding={1}>
          <InputTypeIn
            placeholder="Search groups..."
            variant="internal"
            value={searchQuery}
            leftSearchIcon
            onChange={(e) => setSearchQuery(e.target.value)}
          />
          <Button
            icon={SvgPlusCircle}
            onClick={() => router.push("/admin/groups2/create")}
          >
            New Group
          </Button>
        </Section>
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
