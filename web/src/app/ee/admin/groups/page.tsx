"use client";

import { UserGroupsTable } from "./UserGroupsTable";
import UserGroupCreationForm from "./UserGroupCreationForm";
import { useState } from "react";
import { ThreeDotsLoader } from "@/components/Loading";
import { useConnectorStatus, useUserGroups } from "@/lib/hooks";
import useUsers from "@/hooks/useUsers";
import { useUser } from "@/providers/UserProvider";
import CreateButton from "@/refresh-components/buttons/CreateButton";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { useVectorDbEnabled } from "@/providers/SettingsProvider";

const route = ADMIN_ROUTES.GROUPS;

function Main() {
  const [showForm, setShowForm] = useState(false);
  const vectorDbEnabled = useVectorDbEnabled();

  const { data, isLoading, error, refreshUserGroups } = useUserGroups();

  const {
    data: ccPairs,
    isLoading: isCCPairsLoading,
    error: ccPairsError,
  } = useConnectorStatus(30000, vectorDbEnabled);

  const {
    data: users,
    isLoading: userIsLoading,
    error: usersError,
  } = useUsers({ includeApiKeys: true });

  const { isAdmin } = useUser();

  if (isLoading || (vectorDbEnabled && isCCPairsLoading) || userIsLoading) {
    return <ThreeDotsLoader />;
  }

  if (error || !data) {
    return <div className="text-red-600">Error loading users</div>;
  }

  if (vectorDbEnabled && (ccPairsError || !ccPairs)) {
    return <div className="text-red-600">Error loading connectors</div>;
  }

  if (usersError || !users) {
    return <div className="text-red-600">Error loading users</div>;
  }

  return (
    <>
      {isAdmin && (
        <CreateButton onClick={() => setShowForm(true)}>
          Create New User Group
        </CreateButton>
      )}
      {data.length > 0 && (
        <div className="mt-2">
          <UserGroupsTable userGroups={data} refresh={refreshUserGroups} />
        </div>
      )}
      {showForm && (
        <UserGroupCreationForm
          onClose={() => {
            refreshUserGroups();
            setShowForm(false);
          }}
          users={users.accepted}
          ccPairs={ccPairs ?? []}
        />
      )}
    </>
  );
}

export default function Page() {
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header icon={route.icon} title={route.title} separator />

      <SettingsLayouts.Body>
        <Main />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
