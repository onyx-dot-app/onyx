"use client";
import { use } from "react";

import ResourceErrorPage from "@/sections/error/ResourceErrorPage";
import { refreshDocumentSets, useDocumentSets } from "../hooks";
import { useConnectorStatus, useUserGroups } from "@/lib/hooks";
import { ThreeDotsLoader } from "@/components/Loading";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import CardSection from "@/components/admin/CardSection";
import { DocumentSetCreationForm } from "../DocumentSetCreationForm";
import { useRouter } from "next/navigation";
import { useVectorDbEnabled } from "@/providers/SettingsProvider";

const route = ADMIN_ROUTES.DOCUMENT_SETS;

function Main({ documentSetId }: { documentSetId: number }) {
  const router = useRouter();
  const vectorDbEnabled = useVectorDbEnabled();

  const {
    data: documentSets,
    isLoading: isDocumentSetsLoading,
    error: documentSetsError,
  } = useDocumentSets();

  const {
    data: ccPairs,
    isLoading: isCCPairsLoading,
    error: ccPairsError,
  } = useConnectorStatus(30000, vectorDbEnabled);

  // EE only
  const { data: userGroups, isLoading: userGroupsIsLoading } = useUserGroups();

  if (
    isDocumentSetsLoading ||
    (vectorDbEnabled && isCCPairsLoading) ||
    userGroupsIsLoading
  ) {
    return (
      <div className="flex justify-center items-center min-h-[400px]">
        <ThreeDotsLoader />
      </div>
    );
  }

  if (documentSetsError || !documentSets) {
    return (
      <ResourceErrorPage
        errorType="fetch_error"
        title="Failed to load document sets"
        backHref="/admin/documents/sets"
        backLabel="Back to document sets"
      />
    );
  }

  if (vectorDbEnabled && (ccPairsError || !ccPairs)) {
    return (
      <ResourceErrorPage
        errorType="fetch_error"
        title="Failed to load connectors"
        backHref="/admin/documents/sets"
        backLabel="Back to document sets"
      />
    );
  }

  const documentSet = documentSets.find(
    (documentSet) => documentSet.id === documentSetId
  );
  if (!documentSet) {
    return (
      <ResourceErrorPage
        errorType="not_found"
        title="Document set not found"
        description={`Document set with ID ${documentSetId} could not be found.`}
        backHref="/admin/documents/sets"
        backLabel="Back to document sets"
      />
    );
  }

  return (
    <CardSection>
      <DocumentSetCreationForm
        ccPairs={ccPairs ?? []}
        userGroups={userGroups}
        onClose={() => {
          refreshDocumentSets();
          router.push("/admin/documents/sets");
        }}
        existingDocumentSet={documentSet}
      />
    </CardSection>
  );
}

export default function Page(props: {
  params: Promise<{ documentSetId: string }>;
}) {
  const params = use(props.params);
  const documentSetId = parseInt(params.documentSetId);

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={route.icon}
        title="Edit Document Set"
        separator
        backButton
      />
      <SettingsLayouts.Body>
        <Main documentSetId={documentSetId} />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
