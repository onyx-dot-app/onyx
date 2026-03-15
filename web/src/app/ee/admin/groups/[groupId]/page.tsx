"use client";

import { use } from "react";
import { GroupDisplay } from "./GroupDisplay";
import { useSpecificUserGroup } from "./hook";
import { ThreeDotsLoader } from "@/components/Loading";
import { useConnectorStatus } from "@/lib/hooks";
import useUsers from "@/hooks/useUsers";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { useVectorDbEnabled } from "@/providers/SettingsProvider";

const route = ADMIN_ROUTES.GROUPS;

function Main({ groupId }: { groupId: string }) {
  const vectorDbEnabled = useVectorDbEnabled();
  const {
    userGroup,
    isLoading: userGroupIsLoading,
    error: userGroupError,
    refreshUserGroup,
  } = useSpecificUserGroup(groupId);
  const {
    data: users,
    isLoading: userIsLoading,
    error: usersError,
  } = useUsers({ includeApiKeys: true });
  const {
    data: ccPairs,
    isLoading: isCCPairsLoading,
    error: ccPairsError,
  } = useConnectorStatus(30000, vectorDbEnabled);

  if (
    userGroupIsLoading ||
    userIsLoading ||
    (vectorDbEnabled && isCCPairsLoading)
  ) {
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
  if (vectorDbEnabled && (!ccPairs || ccPairsError)) {
    return <div>Error loading connectors</div>;
  }

  return (
    <>
      <SettingsLayouts.Header
        icon={route.icon}
        title={userGroup.name || "Unknown"}
        separator
        backButton
      />

      <SettingsLayouts.Body>
        <GroupDisplay
          users={users.accepted}
          ccPairs={ccPairs ?? []}
          userGroup={userGroup}
          refreshUserGroup={refreshUserGroup}
        />
      </SettingsLayouts.Body>
    </>
  );
}

export default function Page(props: { params: Promise<{ groupId: string }> }) {
  const params = use(props.params);

  return (
    <SettingsLayouts.Root>
      <Main groupId={params.groupId} />
    </SettingsLayouts.Root>
  );
}
