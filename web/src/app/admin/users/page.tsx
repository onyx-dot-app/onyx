"use client";

import { useState } from "react";
import SimpleTabs from "@/refresh-components/SimpleTabs";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import InvitedUserTable from "@/components/admin/users/InvitedUserTable";
import SignedUpUserTable from "@/components/admin/users/SignedUpUserTable";

import Modal from "@/refresh-components/Modal";
import { ThreeDotsLoader } from "@/components/Loading";
import { AdminPageTitle } from "@/components/admin/Title";
import { toast } from "@/hooks/useToast";
import { errorHandlingFetcher } from "@/lib/fetcher";
import useSWR, { mutate } from "swr";
import { ErrorCallout } from "@/components/ErrorCallout";
import BulkAdd, { EmailInviteStatus } from "@/components/admin/users/BulkAdd";
import Text from "@/refresh-components/texts/Text";
import { InvitedUserSnapshot } from "@/lib/types";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import PendingUsersTable from "@/components/admin/users/PendingUsersTable";
import CreateButton from "@/refresh-components/buttons/CreateButton";
import Button from "@/refresh-components/buttons/Button";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import { Spinner } from "@/components/Spinner";
import { SvgDownloadCloud, SvgUser, SvgUserPlus } from "@opal/icons";
interface CountDisplayProps {
  label: string;
  value: number | null;
  isLoading: boolean;
}

function CountDisplay({ label, value, isLoading }: CountDisplayProps) {
  const displayValue = isLoading
    ? "..."
    : value === null
      ? "-"
      : value.toLocaleString();

  return (
    <div className="flex items-center gap-1 px-1 py-0.5 rounded-06">
      <Text as="p" mainUiMuted text03>
        {label}
      </Text>
      <Text as="p" headingH3 text05>
        {displayValue}
      </Text>
    </div>
  );
}

const UsersTables = ({
  q,
  isDownloadingUsers,
  setIsDownloadingUsers,
}: {
  q: string;
  isDownloadingUsers: boolean;
  setIsDownloadingUsers: (loading: boolean) => void;
}) => {
  const [currentUsersCount, setCurrentUsersCount] = useState<number | null>(
    null
  );
  const [currentUsersLoading, setCurrentUsersLoading] = useState<boolean>(true);

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
      toast.error(`Failed to download all users - ${error}`);
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

  const invitedUsersCount =
    invitedUsers === undefined ? null : invitedUsers.length;
  const pendingUsersCount =
    pendingUsers === undefined ? null : pendingUsers.length;
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

  const tabs = SimpleTabs.generateTabs({
    current: {
      name: "Current Users",
      content: (
        <Card className="w-full">
          <CardHeader>
            <div className="flex justify-between items-center gap-1">
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
              q={q}
              invitedUsersMutate={invitedUsersMutate}
              countDisplay={
                <CountDisplay
                  label="Total users"
                  value={currentUsersCount}
                  isLoading={currentUsersLoading}
                />
              }
              onTotalItemsChange={(count) => setCurrentUsersCount(count)}
              onLoadingChange={(loading) => {
                setCurrentUsersLoading(loading);
                if (loading) {
                  setCurrentUsersCount(null);
                }
              }}
            />
          </CardContent>
        </Card>
      ),
    },
    invited: {
      name: "Invited Users",
      content: (
        <Card className="w-full">
          <CardHeader>
            <div className="flex justify-between items-center gap-1">
              <CardTitle>Invited Users</CardTitle>
              <CountDisplay
                label="Total invited"
                value={invitedUsersCount}
                isLoading={invitedUsersLoading}
              />
            </div>
          </CardHeader>
          <CardContent>
            <InvitedUserTable
              users={invitedUsers || []}
              mutate={invitedUsersMutate}
              error={invitedUsersError}
              isLoading={invitedUsersLoading}
              q={q}
            />
          </CardContent>
        </Card>
      ),
    },
    ...(NEXT_PUBLIC_CLOUD_ENABLED && {
      pending: {
        name: "Pending Users",
        content: (
          <Card>
            <CardHeader>
              <div className="flex justify-between items-center gap-1">
                <CardTitle>Pending Users</CardTitle>
                <CountDisplay
                  label="Total pending"
                  value={pendingUsersCount}
                  isLoading={pendingUsersLoading}
                />
              </div>
            </CardHeader>
            <CardContent>
              <PendingUsersTable
                users={pendingUsers || []}
                mutate={pendingUsersMutate}
                error={pendingUsersError}
                isLoading={pendingUsersLoading}
                q={q}
              />
            </CardContent>
          </Card>
        ),
      },
    }),
  });

  return <SimpleTabs tabs={tabs} defaultValue="current" />;
};

const SearchableTables = () => {
  const [query, setQuery] = useState("");
  const [isDownloadingUsers, setIsDownloadingUsers] = useState(false);

  return (
    <div>
      {isDownloadingUsers && <Spinner />}
      <div className="flex flex-col gap-y-4">
        <div className="flex flex-row items-center gap-2">
          <InputTypeIn
            placeholder="Search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          <AddUserButton />
        </div>
        <UsersTables
          q={query}
          isDownloadingUsers={isDownloadingUsers}
          setIsDownloadingUsers={setIsDownloadingUsers}
        />
      </div>
    </div>
  );
};

function AddUserButton() {
  const [bulkAddUsersModal, setBulkAddUsersModal] = useState(false);

  const onSuccess = (emailInviteStatus: EmailInviteStatus) => {
    mutate(
      (key) => typeof key === "string" && key.startsWith("/api/manage/users")
    );
    setBulkAddUsersModal(false);
    if (emailInviteStatus === "NOT_CONFIGURED") {
      toast.warning(
        "Users added, but no email notification was sent. There is no SMTP server set up for email sending."
      );
    } else if (emailInviteStatus === "SEND_FAILED") {
      toast.warning(
        "Users added, but email sending failed. Check your SMTP configuration and try again."
      );
    } else {
      toast.success("Users invited!");
    }
  };

  const onFailure = async (res: Response) => {
    const error = (await res.json()).detail;
    toast.error(`Failed to invite users - ${error}`);
  };

  const handleInviteClick = () => {
    setBulkAddUsersModal(true);
  };

  return (
    <>
      <CreateButton primary onClick={handleInviteClick}>
        Invite Users
      </CreateButton>

      {bulkAddUsersModal && (
        <Modal open onOpenChange={() => setBulkAddUsersModal(false)}>
          <Modal.Content>
            <Modal.Header
              icon={SvgUserPlus}
              title="Bulk Add Users"
              onClose={() => setBulkAddUsersModal(false)}
            />
            <Modal.Body>
              <div className="flex flex-col gap-2">
                <Text as="p">
                  Add the email addresses to import, separated by whitespaces.
                  Invited users will be able to login to this domain with their
                  email address.
                </Text>
                <BulkAdd onSuccess={onSuccess} onFailure={onFailure} />
              </div>
            </Modal.Body>
          </Modal.Content>
        </Modal>
      )}
    </>
  );
}

const Page = () => {
  return (
    <>
      <AdminPageTitle title="Manage Users" icon={SvgUser} />
      <SearchableTables />
    </>
  );
};

export default Page;
