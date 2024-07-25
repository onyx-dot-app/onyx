"use client";

import { GroupsIcon } from "@/components/icons/icons";
import { UserGroupsTable } from "./UserGroupsTable";
import { UserGroupCreationForm } from "./UserGroupCreationForm";
import { usePopup } from "@/components/admin/connectors/Popup";
import { useState } from "react";
import { ThreeDotsLoader } from "@/components/Loading";
import {
  useConnectorCredentialIndexingStatus,
  useUserGroups,
  useUsers,
} from "@/lib/hooks";
import { AdminPageTitle } from "@/components/admin/Title";
import { Button, Divider } from "@tremor/react";

const Main = () => {
  const { popup, setPopup } = usePopup();
  const [showForm, setShowForm] = useState(false);

  const { data, isLoading, error, refreshUserGroups } = useUserGroups();

  const {
    data: ccPairs,
    isLoading: isCCPairsLoading,
    error: ccPairsError,
  } = useConnectorCredentialIndexingStatus();

  const {
    data: users,
    isLoading: userIsLoading,
    error: usersError,
  } = useUsers();

  if (isLoading || isCCPairsLoading || userIsLoading) {
    return <ThreeDotsLoader />;
  }

  if (error || !data) {
    return <div className="text-red-600">Error loading users</div>;
  }

  if (ccPairsError || !ccPairs) {
    return <div className="text-red-600">Error loading connectors</div>;
  }

  if (usersError || !users) {
    return <div className="text-red-600">Error loading users</div>;
  }

  return (
    <>
      {popup}
      <div className="my-3">
        <Button size="xs" color="green" onClick={() => setShowForm(true)}>
          Create New User Group
        </Button>
      </div>
      {data.length > 0 && (
        <div>
          <Divider />
          <UserGroupsTable
            userGroups={data}
            setPopup={setPopup}
            refresh={refreshUserGroups}
          />
        </div>
      )}
      {showForm && (
        <UserGroupCreationForm
          onClose={() => {
            refreshUserGroups();
            setShowForm(false);
          }}
          setPopup={setPopup}
          users={users.accepted}
          ccPairs={ccPairs}
        />
      )}
    </>
  );
};

const Page = () => {
  return (
    <div className="mx-auto container">
      <AdminPageTitle
        title="Manage User Groups"
        icon={<GroupsIcon size={32} />}
      />

      <Main />
    </div>
  );
};

export default Page;
