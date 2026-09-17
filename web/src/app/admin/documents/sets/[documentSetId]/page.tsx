"use client";
import { use } from "react";
import { useTranslations } from "next-intl";

import { ErrorCallout } from "@/components/ErrorCallout";
import { refreshDocumentSets, useDocumentSets } from "../hooks";
import { useConnectorStatus } from "@/lib/hooks";
import { PageLoader } from "@opal/layouts";
import { SettingsLayouts } from "@opal/layouts";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import CardSection from "@/components/admin/CardSection";
import { DocumentSetCreationForm } from "../DocumentSetCreationForm";
import { useRouter } from "next/navigation";
import { useSettings } from "@/lib/settings/hooks";

const route = ADMIN_ROUTES.DOCUMENT_SETS;

function Main({ documentSetId }: { documentSetId: number }) {
  const t = useTranslations("admin.documents");
  const router = useRouter();
  const { vectorDbEnabled } = useSettings();

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

  if (isDocumentSetsLoading || (vectorDbEnabled && isCCPairsLoading)) {
    return (
      <div className="flex justify-center items-center min-h-[400px]">
        <PageLoader />
      </div>
    );
  }

  if (documentSetsError || !documentSets) {
    return (
      <ErrorCallout
        errorTitle={t("sets.fetchSetsFailed.title")}
        errorMsg={documentSetsError}
      />
    );
  }

  if (vectorDbEnabled && (ccPairsError || !ccPairs)) {
    return (
      <ErrorCallout
        errorTitle={t("sets.fetchConnectorsFailed.title")}
        errorMsg={ccPairsError}
      />
    );
  }

  const documentSet = documentSets.find(
    (documentSet) => documentSet.id === documentSetId
  );
  if (!documentSet) {
    return (
      <ErrorCallout
        errorTitle={t("sets.notFound.title")}
        errorMsg={t("sets.notFound.message", { id: String(documentSetId) })}
      />
    );
  }

  return (
    <CardSection>
      <DocumentSetCreationForm
        ccPairs={ccPairs ?? []}
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
  const t = useTranslations("admin.documents");
  const params = use(props.params);
  const documentSetId = parseInt(params.documentSetId);

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={route.icon}
        title={t("sets.edit.header.title")}
        divider
        backButton
      />
      <SettingsLayouts.Body>
        <Main documentSetId={documentSetId} />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
