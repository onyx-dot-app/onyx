"use client";

import { useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import InvitedUserTable from "@/components/admin/users/InvitedUserTable";
import SignedUpUserTable from "@/components/admin/users/SignedUpUserTable";

import { Modal } from "@/components/Modal";
import { ThreeDotsLoader } from "@/components/Loading";
import { AdminPageTitle } from "@/components/admin/Title";
import { usePopup, PopupSpec } from "@/components/admin/connectors/Popup";
import { UsersIcon } from "@/components/icons/icons";
import { errorHandlingFetcher } from "@/lib/fetcher";
import useSWR, { mutate } from "swr";
import { ErrorCallout } from "@/components/ErrorCallout";
import BulkAdd from "@/components/admin/users/BulkAdd";
import Text from "@/components/ui/text";
import { InvitedUserSnapshot } from "@/lib/types";
import { ConfirmEntityModal } from "@/components/modals/ConfirmEntityModal";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import PendingUsersTable from "@/components/admin/users/PendingUsersTable";
import CreateButton from "@/refresh-components/buttons/CreateButton";
import Button from "@/refresh-components/buttons/Button";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import { Spinner } from "@/components/Spinner";
import SvgDownloadCloud from "@/icons/download-cloud";

const UsersTables = ({
  q,
  setPopup,
  isDownloadingUsers,
  setIsDownloadingUsers,
}: {
  q: string;
  setPopup: (spec: PopupSpec) => void;
  isDownloadingUsers: boolean;
  setIsDownloadingUsers: (loading: boolean) => void;
}) => {
  const downloadAllUsers = async () => {
    setIsDownloadingUsers(true);
    const startTime = Date.now();
    const minDurationMsForSpinner = 1000;
    try {
      const response = await fetch("/api/manage/users/download");
      if (!response.ok) {
        throw new Error("Failed to download all users");
      }
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const anchor_tag = document.createElement("a");
      anchor_tag.href = url;
      anchor_tag.download = "users.csv";
      document.body.appendChild(anchor_tag);
      anchor_tag.click();
      //Clean up URL after download to avoid memory leaks
      window.URL.revokeObjectURL(url);
      document.body.removeChild(anchor_tag);
    } catch (error) {
      setPopup({
        message: `Failed to download all users - ${error}`,
        type: "error",
      });
    } finally {
      //Ensure spinner is visible for at least 1 second
      //This is to avoid the spinner disappearing too quickly
      const endTime = Date.now();
      const duration = endTime - startTime;
      await new Promise((resolve) =>
        setTimeout(resolve, minDurationMsForSpinner - duration)
      );
      setIsDownloadingUsers(false);
    }
  };

  const {
    data: invitedUsers,
    error: invitedUsersError,
    isLoading: invitedUsersLoading,
    mutate: invitedUsersMutate,
  } = useSWR<InvitedUserSnapshot[]>(
    "/api/manage/users/invited",
    errorHandlingFetcher
  );

  const { data: validDomains, error: domainsError } = useSWR<string[]>(
    "/api/manage/admin/valid-domains",
    errorHandlingFetcher
  );

  const {
    data: pendingUsers,
    error: pendingUsersError,
    isLoading: pendingUsersLoading,
    mutate: pendingUsersMutate,
  } = useSWR<InvitedUserSnapshot[]>(
    NEXT_PUBLIC_CLOUD_ENABLED ? "/api/tenants/users/pending" : null,
    errorHandlingFetcher
  );
  // Show loading animation only during the initial data fetch
  if (!validDomains) {
    return <ThreeDotsLoader />;
  }

  if (domainsError) {
    return (
      <ErrorCallout
        errorTitle="Error loading valid domains"
        errorMsg={domainsError?.info?.detail}
      />
    );
  }

  return (
    <Tabs defaultValue="current">
      <TabsList>
        <TabsTrigger value="current">Current Users</TabsTrigger>
        <TabsTrigger value="invited">Invited Users</TabsTrigger>
        {NEXT_PUBLIC_CLOUD_ENABLED && (
          <TabsTrigger value="pending">Pending Users</TabsTrigger>
        )}
      </TabsList>

      <TabsContent value="current">
        <Card>
          <CardHeader>
            <div className="flex justify-between items-center">
              <CardTitle>Current Users</CardTitle>
              <Button
                leftIcon={SvgDownloadCloud}
                disabled={isDownloadingUsers}
                onClick={() => downloadAllUsers()}
              >
                {isDownloadingUsers ? "Downloading..." : "Download CSV"}
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            <SignedUpUserTable
              invitedUsers={invitedUsers || []}
              setPopup={setPopup}
              q={q}
              invitedUsersMutate={invitedUsersMutate}
            />
          </CardContent>
        </Card>
      </TabsContent>
      <TabsContent value="invited">
        <Card>
          <CardHeader>
            <CardTitle>Invited Users</CardTitle>
          </CardHeader>
          <CardContent>
            <InvitedUserTable
              users={invitedUsers || []}
              setPopup={setPopup}
              mutate={invitedUsersMutate}
              error={invitedUsersError}
              isLoading={invitedUsersLoading}
              q={q}
            />
          </CardContent>
        </Card>
      </TabsContent>
      {NEXT_PUBLIC_CLOUD_ENABLED && (
        <TabsContent value="pending">
          <Card>
            <CardHeader>
              <CardTitle>Pending Users</CardTitle>
            </CardHeader>
            <CardContent>
              <PendingUsersTable
                users={pendingUsers || []}
                setPopup={setPopup}
                mutate={pendingUsersMutate}
                error={pendingUsersError}
                isLoading={pendingUsersLoading}
                q={q}
              />
            </CardContent>
          </Card>
        </TabsContent>
      )}
    </Tabs>
  );
};

const SearchableTables = () => {
  const { popup, setPopup } = usePopup();
  const [query, setQuery] = useState("");
  const [isDownloadingUsers, setIsDownloadingUsers] = useState(false);

  return (
    <div>
      {isDownloadingUsers && <Spinner />}
      {popup}
      <div className="flex flex-col gap-y-4">
        <div className="flex flex-row items-center gap-spacing-interline">
          <InputTypeIn
            placeholder="Search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          <AddUserButton setPopup={setPopup} />
        </div>
        <UsersTables
          q={query}
          setPopup={setPopup}
          isDownloadingUsers={isDownloadingUsers}
          setIsDownloadingUsers={setIsDownloadingUsers}
        />
      </div>
    </div>
  );
};

const AddUserButton = ({
  setPopup,
}: {
  setPopup: (spec: PopupSpec) => void;
}) => {
  const [bulkAddUsersModal, setBulkAddUsersModal] = useState(false);
  const [firstUserConfirmationModal, setFirstUserConfirmationModal] =
    useState(false);

  const { data: invitedUsers } = useSWR<InvitedUserSnapshot[]>(
    "/api/manage/users/invited",
    errorHandlingFetcher
  );

  const onSuccess = () => {
    mutate(
      (key) => typeof key === "string" && key.startsWith("/api/manage/users")
    );
    setBulkAddUsersModal(false);
    setPopup({
      message: "Users invited!",
      type: "success",
    });
  };

  const onFailure = async (res: Response) => {
    const error = (await res.json()).detail;
    setPopup({
      message: `Failed to invite users - ${error}`,
      type: "error",
    });
  };

  const handleInviteClick = () => {
    if (
      !NEXT_PUBLIC_CLOUD_ENABLED &&
      invitedUsers &&
      invitedUsers.length === 0
    ) {
      setFirstUserConfirmationModal(true);
    } else {
      setBulkAddUsersModal(true);
    }
  };

  const handleConfirmFirstInvite = () => {
    setFirstUserConfirmationModal(false);
    setBulkAddUsersModal(true);
  };

  return (
    <>
      <CreateButton primary onClick={handleInviteClick}>
        Invite Users
      </CreateButton>

      {firstUserConfirmationModal && (
        <ConfirmEntityModal
          entityType="First User Invitation"
          entityName="your Access Logic"
          onClose={() => setFirstUserConfirmationModal(false)}
          onSubmit={handleConfirmFirstInvite}
          additionalDetails="After inviting the first user, only invited users will be able to join this platform. This is a security measure to control access to your team."
          actionButtonText="Continue"
        />
      )}

      {bulkAddUsersModal && (
        <Modal
          title="Bulk Add Users"
          onOutsideClick={() => setBulkAddUsersModal(false)}
        >
          <div className="flex flex-col gap-spacing-interline">
            <Text>
              Add the email addresses to import, separated by whitespaces.
              Invited users will be able to login to this domain with their
              email address.
            </Text>
            <BulkAdd onSuccess={onSuccess} onFailure={onFailure} />
          </div>
        </Modal>
      )}
    </>
  );
};

const Page = () => {
  return (
    <div className="mx-auto container">
      <AdminPageTitle title="Manage Users" icon={<UsersIcon size={32} />} />
      <SearchableTables />
    </div>
  );
};

export default Page;
