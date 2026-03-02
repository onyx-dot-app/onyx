"use client";

import { use } from "react";
import { GroupDisplay } from "./GroupDisplay";
import { useSpecificUserGroup } from "./hook";
import { ThreeDotsLoader } from "@/components/Loading";
import { useConnectorStatus } from "@/lib/hooks";
import useUsers from "@/hooks/useUsers";
import { SvgUsers } from "@opal/icons";
import * as SettingsLayouts from "@/layouts/settings-layouts";

export default function Page(props: { params: Promise<{ groupId: string }> }) {
  const params = use(props.params);

  const {
    userGroup,
    isLoading: userGroupIsLoading,
    error: userGroupError,
    refreshUserGroup,
  } = useSpecificUserGroup(params.groupId);
  const {
    data: users,
    isLoading: userIsLoading,
    error: usersError,
  } = useUsers({ includeApiKeys: true });
  const {
    data: ccPairs,
    isLoading: isCCPairsLoading,
    error: ccPairsError,
  } = useConnectorStatus();

  if (userGroupIsLoading || userIsLoading || isCCPairsLoading) {
    return (
      <div className="h-full">
        <div className="my-auto">
          <ThreeDotsLoader />
        </div>
      </div>
    );
  }

  if (!userGroup || userGroupError) {
    return <div>Error loading user group</div>;
  }
  if (!users || usersError) {
    return <div>Error loading users</div>;
  }
  if (!ccPairs || ccPairsError) {
    return <div>Error loading connectors</div>;
  }

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgUsers}
        title={userGroup.name || "Unknown"}
        separator
        backButton
      />

      <SettingsLayouts.Body>
        {userGroup ? (
          <GroupDisplay
            users={users.accepted}
            ccPairs={ccPairs}
            userGroup={userGroup}
            refreshUserGroup={refreshUserGroup}
          />
        ) : (
          <div>Unable to fetch User Group :(</div>
        )}
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
