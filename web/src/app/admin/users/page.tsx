"use client";
import InvitedUserTable from "@/components/admin/users/InvitedUserTable";
import SignedUpUserTable from "@/components/admin/users/SignedUpUserTable";
import { SearchBar } from "@/components/search/SearchBar";
import { useState } from "react";
import { FiPlusSquare } from "react-icons/fi";
import { Modal } from "@/components/Modal";

import { Button, Text } from "@tremor/react";
import { LoadingAnimation } from "@/components/Loading";
import { AdminPageTitle } from "@/components/admin/Title";
import { usePopup, PopupSpec } from "@/components/admin/connectors/Popup";
import { UsersIcon } from "@/components/icons/icons";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { type User, UserStatus } from "@/lib/types";
import useSWR, { mutate } from "swr";
import { ErrorCallout } from "@/components/ErrorCallout";
import { HidableSection } from "@/app/admin/assistants/HidableSection";
import BulkAdd from "@/components/admin/users/BulkAdd";
import { UsersResponse } from "@/lib/users/interfaces";

const ValidDomainsDisplay = ({ validDomains }: { validDomains: string[] }) => {
  if (!validDomains.length) {
    return (
      <div className="text-sm">
        No invited users. Anyone can sign up with a valid email address. To
        restrict access you can:
        <div className="flex flex-wrap ml-2 mt-1">
          (1) Invite users above. Once a user has been invited, only emails that
          have explicitly been invited will be able to sign-up.
        </div>
        <div className="mt-1 ml-2">
          (2) Set the{" "}
          <b className="font-mono w-fit h-fit">VALID_EMAIL_DOMAINS</b>{" "}
          environment variable to a comma separated list of email domains. This
          will restrict access to users with email addresses from these domains.
        </div>
      </div>
    );
  }

  return (
    <div className="text-sm">
      No invited users. Anyone with an email address with any of the following
      domains can sign up: <i>{validDomains.join(", ")}</i>.
      <div className="mt-2">
        To further restrict access you can invite users above. Once a user has
        been invited, only emails that have explicitly been invited will be able
        to sign-up.
      </div>
    </div>
  );
};

const UsersTables = ({
  q,
  setPopup,
}: {
  q: string;
  setPopup: (spec: PopupSpec) => void;
}) => {
  const [invitedPage, setInvitedPage] = useState(1);
  const [acceptedPage, setAcceptedPage] = useState(1);
  const { data, isLoading, mutate, error } = useSWR<UsersResponse>(
    `/api/manage/users?q=${encodeURI(q)}&accepted_page=${
      acceptedPage - 1
    }&invited_page=${invitedPage - 1}`,
    errorHandlingFetcher
  );
  const {
    data: validDomains,
    isLoading: isLoadingDomains,
    error: domainsError,
  } = useSWR<string[]>("/api/manage/admin/valid-domains", errorHandlingFetcher);

  if (isLoading || isLoadingDomains) {
    return <LoadingAnimation text="Loading" />;
  }

  if (error || !data) {
    return (
      <ErrorCallout
        errorTitle="Error loading users"
        errorMsg={error?.info?.detail}
      />
    );
  }

  if (domainsError || !validDomains) {
    return (
      <ErrorCallout
        errorTitle="Error loading valid domains"
        errorMsg={domainsError?.info?.detail}
      />
    );
  }

  const { accepted, invited, accepted_pages, invited_pages } = data;

  // remove users that are already accepted
  const finalInvited = invited.filter(
    (user) => !accepted.map((u) => u.email).includes(user.email)
  );

  return (
    <>
      <HidableSection sectionTitle="Invited Users">
        {invited.length > 0 ? (
          finalInvited.length > 0 ? (
            <InvitedUserTable
              users={finalInvited}
              setPopup={setPopup}
              currentPage={invitedPage}
              onPageChange={setInvitedPage}
              totalPages={invited_pages}
              mutate={mutate}
            />
          ) : (
            <div className="text-sm">
              To invite additional teammates, use the <b>Invite Users</b> button
              above!
            </div>
          )
        ) : (
          <ValidDomainsDisplay validDomains={validDomains} />
        )}
      </HidableSection>
      <SignedUpUserTable
        users={accepted}
        setPopup={setPopup}
        currentPage={acceptedPage}
        onPageChange={setAcceptedPage}
        totalPages={accepted_pages}
        mutate={mutate}
      />
    </>
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
      <Button className="w-fit" onClick={() => setModal(true)}>
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
