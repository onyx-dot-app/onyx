"use client";

import * as SettingsLayouts from "@/layouts/settings-layouts";
import { SvgBookOpen } from "@opal/icons";
import { DocumentSetCreationForm } from "../DocumentSetCreationForm";
import { useConnectorStatus, useUserGroups } from "@/lib/hooks";
import { ThreeDotsLoader } from "@/components/Loading";
import { ErrorCallout } from "@/components/ErrorCallout";
import { useRouter } from "next/navigation";
import { refreshDocumentSets } from "../hooks";
import CardSection from "@/components/admin/CardSection";

function Main() {
  const router = useRouter();

  const {
    data: ccPairs,
    isLoading: isCCPairsLoading,
    error: ccPairsError,
  } = useConnectorStatus();

  // EE only
  const { data: userGroups, isLoading: userGroupsIsLoading } = useUserGroups();

  if (isCCPairsLoading || userGroupsIsLoading) {
    return (
      <div className="flex justify-center items-center min-h-[400px]">
        <ThreeDotsLoader />
      </div>
    );
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
      <CardSection>
        <DocumentSetCreationForm
          ccPairs={ccPairs}
          userGroups={userGroups}
          onClose={() => {
            refreshDocumentSets();
            router.push("/admin/documents/sets");
          }}
        />
      </CardSection>
    </>
  );
}

const Page = () => {
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgBookOpen}
        title="New Document Set"
        separator
        backButton
      />
      <SettingsLayouts.Body>
        <Main />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
};

export default Page;
