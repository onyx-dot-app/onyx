"use client";

import * as SettingsLayouts from "@/layouts/settings-layouts";
import { ADMIN_ROUTE_CONFIG, ADMIN_PATHS } from "@/lib/admin-routes";
import { DocumentSetCreationForm } from "../DocumentSetCreationForm";
import { useConnectorStatus, useUserGroups } from "@/lib/hooks";
import { ThreeDotsLoader } from "@/components/Loading";
import { ErrorCallout } from "@/components/ErrorCallout";
import { useRouter } from "next/navigation";
import { refreshDocumentSets } from "../hooks";
import CardSection from "@/components/admin/CardSection";
import { useSettingsContext } from "@/providers/SettingsProvider";

function Main() {
  const router = useRouter();
  const settings = useSettingsContext();
  const vectorDbEnabled = settings?.settings.vector_db_enabled !== false;

  const {
    data: ccPairs,
    isLoading: isCCPairsLoading,
    error: ccPairsError,
  } = useConnectorStatus(30000, vectorDbEnabled);

  // EE only
  const { data: userGroups, isLoading: userGroupsIsLoading } = useUserGroups();

  if ((vectorDbEnabled && isCCPairsLoading) || userGroupsIsLoading) {
    return (
      <div className="flex justify-center items-center min-h-[400px]">
        <ThreeDotsLoader />
      </div>
    );
  }

  if (vectorDbEnabled && (ccPairsError || !ccPairs)) {
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
          ccPairs={ccPairs ?? []}
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

export default function Page() {
  const route = ADMIN_ROUTE_CONFIG[ADMIN_PATHS.DOCUMENT_SETS]!;

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={route.icon}
        title="New Document Set"
        separator
        backButton
      />
      <SettingsLayouts.Body>
        <Main />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
