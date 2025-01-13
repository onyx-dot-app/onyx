"use client";
import { useEffect, useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import InvitedUserTable from "@/components/admin/users/InvitedUserTable";
import SignedUpUserTable from "@/components/admin/users/SignedUpUserTable";
import { SearchBar } from "@/components/search/SearchBar";
import { FiPlusSquare } from "react-icons/fi";
import { Modal } from "@/components/Modal";
import { LoadingAnimation } from "@/components/Loading";
import { AdminPageTitle } from "@/components/admin/Title";
import { usePopup, PopupSpec } from "@/components/admin/connectors/Popup";
import { UsersIcon } from "@/components/icons/icons";
import { errorHandlingFetcher } from "@/lib/fetcher";
import useSWR, { mutate } from "swr";
import { ErrorCallout } from "@/components/ErrorCallout";
import BulkAdd from "@/components/admin/users/BulkAdd";
import { UsersResponse } from "@/lib/users/interfaces";
import SlackUserTable from "@/components/admin/users/SlackUserTable";
import Text from "@/components/ui/text";

const UsersTables = ({
  q,
  setPopup,
}: {
  q: string;
  setPopup: (spec: PopupSpec) => void;
}) => {
  const [invitedPage, setInvitedPage] = useState(1);
  const [acceptedPage, setAcceptedPage] = useState(1);
  const [slackUsersPage, setSlackUsersPage] = useState(1);

  const [usersData, setUsersData] = useState<UsersResponse | undefined>(
    undefined
  );
  const [domainsData, setDomainsData] = useState<string[] | undefined>(
    undefined
  );

  const { data, error, mutate } = useSWR<UsersResponse>(
    `/api/manage/users?q=${encodeURIComponent(q)}&accepted_page=${
      acceptedPage - 1
    }&invited_page=${invitedPage - 1}&slack_users_page=${slackUsersPage - 1}`,
    errorHandlingFetcher
  );

  const { data: validDomains, error: domainsError } = useSWR<string[]>(
    "/api/manage/admin/valid-domains",
    errorHandlingFetcher
  );

  useEffect(() => {
    if (data) {
      setUsersData(data);
    }
  }, [data]);

  useEffect(() => {
    if (validDomains) {
      setDomainsData(validDomains);
    }
  }, [validDomains]);

  const activeData = data ?? usersData;
  const activeDomains = validDomains ?? domainsData;

  // Show loading animation only during the initial data fetch
  if (!activeData || !activeDomains) {
    return <LoadingAnimation text="Loading" />;
  }

  if (error) {
    return (
      <ErrorCallout
        errorTitle="Error loading users"
        errorMsg={error?.info?.detail}
      />
    );
  }

  if (domainsError) {
    return (
      <ErrorCallout
        errorTitle="Error loading valid domains"
        errorMsg={domainsError?.info?.detail}
      />
    );
  }

  const {
    accepted,
    invited,
    accepted_pages,
    invited_pages,
    slack_users,
    slack_users_pages,
  } = activeData;

  const finalInvited = invited.filter(
    (user) => !accepted.some((u) => u.email === user.email)
  );

  return (
    <Tabs defaultValue="invited">
      <TabsList>
        <TabsTrigger value="invited">Invited Users</TabsTrigger>
        <TabsTrigger value="current">Current Users</TabsTrigger>
        <TabsTrigger value="onyxbot">OnyxBot Users</TabsTrigger>
      </TabsList>

      <TabsContent value="invited">
        <Card>
          <CardHeader>
            <CardTitle>Invited Users</CardTitle>
          </CardHeader>
          <CardContent>
            {finalInvited.length > 0 ? (
              <InvitedUserTable
                users={finalInvited}
                setPopup={setPopup}
                currentPage={invitedPage}
                onPageChange={setInvitedPage}
                totalPages={invited_pages}
                mutate={mutate}
              />
            ) : (
              <p>Users that have been invited will show up here</p>
            )}
          </CardContent>
        </Card>
      </TabsContent>

      <TabsContent value="current">
        <Card>
          <CardHeader>
            <CardTitle>Current Users</CardTitle>
          </CardHeader>
          <CardContent>
            {accepted.length > 0 ? (
              <SignedUpUserTable
                users={accepted}
                setPopup={setPopup}
                currentPage={acceptedPage}
                onPageChange={setAcceptedPage}
                totalPages={accepted_pages}
                mutate={mutate}
              />
            ) : (
              <p>Users that have an account will show up here</p>
            )}
          </CardContent>
        </Card>
      </TabsContent>

      <TabsContent value="onyxbot">
        <Card>
          <CardHeader>
            <CardTitle>OnyxBot Users</CardTitle>
          </CardHeader>
          <CardContent>
            {slack_users.length > 0 ? (
              <SlackUserTable
                setPopup={setPopup}
                currentPage={slackUsersPage}
                onPageChange={setSlackUsersPage}
                totalPages={slack_users_pages}
                invitedUsers={finalInvited}
                slackusers={slack_users}
                mutate={mutate}
              />
            ) : (
              <p>Slack-only users will show up here</p>
            )}
          </CardContent>
        </Card>
      </TabsContent>
    </Tabs>
  );
};

const SearchableTables = () => {
  const { popup, setPopup } = usePopup();
  const [query, setQuery] = useState("");
  const [q, setQ] = useState("");

  return (
    <div>
      {popup}

      <div className="flex flex-col gap-y-4">
        <div className="flex gap-x-4">
          <AddUserButton setPopup={setPopup} />
          <div className="flex-grow">
            <SearchBar
              query={query}
              setQuery={setQuery}
              onSearch={() => setQ(query)}
            />
          </div>
        </div>
        <UsersTables q={q} setPopup={setPopup} />
      </div>
    </div>
  );
};

const AddUserButton = ({
  setPopup,
}: {
  setPopup: (spec: PopupSpec) => void;
}) => {
  const [modal, setModal] = useState(false);
  const onSuccess = () => {
    mutate(
      (key) => typeof key === "string" && key.startsWith("/api/manage/users")
    );
    setModal(false);
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
  return (
    <>
      <Button className="my-auto w-fit" onClick={() => setModal(true)}>
        <div className="flex">
          <FiPlusSquare className="my-auto mr-2" />
          Invite Users
        </div>
      </Button>

      {modal && (
        <Modal title="Bulk Add Users" onOutsideClick={() => setModal(false)}>
          <div className="flex flex-col gap-y-4">
            <Text className="font-medium text-base">
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
