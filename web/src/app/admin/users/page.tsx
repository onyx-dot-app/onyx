"use client";
import InvitedUserTable from "@/components/admin/users/InvitedUserTable";
import SignedUpUserTable from "@/components/admin/users/SignedUpUserTable";
import { SearchBar } from "@/components/search/SearchBar";
import { useState, useEffect } from "react";
import { FiPlusSquare } from "react-icons/fi";
import { Modal } from "@/components/Modal";

import { Button } from "@/components/ui/button";
import Text from "@/components/ui/text";
import { AdminPageTitle } from "@/components/admin/Title";
import { usePopup, PopupSpec } from "@/components/admin/connectors/Popup";
import { UsersIcon } from "@/components/icons/icons";
import { mutate } from "swr";
import { HidableSection } from "@/app/admin/assistants/HidableSection";
import BulkAdd from "@/components/admin/users/BulkAdd";

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

const useDebounce = <T,>(value: T, delay: number): [T, (value: T) => void] => {
  const [debouncedValue, setDebouncedValue] = useState<T>(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedValue(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);

  return [debouncedValue, setDebouncedValue] as const;
};

const SearchableTables = () => {
  const { popup, setPopup } = usePopup();
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useDebounce(searchQuery, 300);

  return (
    <div>
      {popup}

      <div className="flex flex-col gap-y-4">
        <div className="flex gap-x-4">
          <AddUserButton setPopup={setPopup} q={debouncedQuery} />
          <div className="flex-grow">
            <SearchBar
              query={searchQuery}
              setQuery={setSearchQuery}
              onSearch={() => setDebouncedQuery(searchQuery)}
            />
          </div>
        </div>
        <SignedUpUserTable q={debouncedQuery} setPopup={setPopup} />
      </div>
    </div>
  );
};

const AddUserButton = ({
  setPopup,
  q,
}: {
  setPopup: (spec: PopupSpec) => void;
  q: string;
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
      <Button
        className="my-auto w-fit"
        variant="submit"
        onClick={() => setModal(true)}
      >
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
            <HidableSection sectionTitle="Invited Users">
              <InvitedUserTable setPopup={setPopup} q={q} />
            </HidableSection>
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
