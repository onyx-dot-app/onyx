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
import { BackButton } from "@/components/BackButton";
import { ErrorCallout } from "@/components/ErrorCallout";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { refreshDocumentSets } from "../hooks";
import CardSection from "@/components/admin/CardSection";

function Main() {
  const { popup, setPopup } = usePopup();
  const router = useRouter();

  const {
    data: ccPairs,
    isLoading: isCCPairsLoading,
    error: ccPairsError,
  } = useConnectorCredentialIndexingStatus();

  // EE only
  const [userGroupsIsLoadingState, setUserGroupsIsLoadingState] =
    useState(true);
  const { data: userGroups, isLoading: userGroupsIsLoading } = useUserGroups();
  if (userGroupsIsLoadingState && !userGroupsIsLoading) {
    setUserGroupsIsLoadingState(false);
  }

  if (isCCPairsLoading || userGroupsIsLoadingState) {
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

      <CardSection>
        <DocumentSetCreationForm
          ccPairs={ccPairs}
          userGroups={userGroups}
          onClose={() => {
            refreshDocumentSets();
            router.push("/admin/documents/sets");
          }}
          setPopup={setPopup}
        />
      </CardSection>
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
