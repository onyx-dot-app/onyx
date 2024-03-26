"use client";

import { AdminPageTitle } from "@/components/admin/Title";
import { BookmarkIcon } from "@/components/icons/icons";
import { DocumentSetCreationForm } from "../DocumentSetCreationForm";
import {
  useConnectorCredentialIndexingStatus,
  useUserGroups,
} from "@/lib/hooks";
import { ThreeDotsLoader } from "@/components/Loading";
import { usePopup } from "@/components/admin/connectors/Popup";
import { Card } from "@tremor/react";
import { BackButton } from "@/components/BackButton";
import { ErrorCallout } from "@/components/ErrorCallout";
import { useRouter } from "next/navigation";
import { UserGroup } from "@/lib/types";

function Main() {
  const { popup, setPopup } = usePopup();
  const router = useRouter();

  const {
    data: ccPairs,
    isLoading: isCCPairsLoading,
    error: ccPairsError,
  } = useConnectorCredentialIndexingStatus();

  // EE only
  const { data: userGroups, isLoading: userGroupsIsLoading } = useUserGroups();

  if (isCCPairsLoading || userGroupsIsLoading) {
    return <ThreeDotsLoader />;
  }

  if (ccPairsError || !ccPairs) {
    return (
      <ErrorCallout
        errorTitle="Failed to fetch Connectors"
        errorMsg={ccPairsError}
      />
    );
  }

  return (
    <>
      {popup}

      <Card>
        <DocumentSetCreationForm
          ccPairs={ccPairs}
          userGroups={userGroups}
          onClose={() => {
            router.push("/admin/documents/sets");
          }}
          setPopup={setPopup}
        />
      </Card>
    </>
  );
}

const Page = () => {
  return (
    <div className="container mx-auto">
      <BackButton />

      <AdminPageTitle
        icon={<BookmarkIcon size={32} />}
        title="New Document Set"
      />

      <Main />
    </div>
  );
};

export default Page;
