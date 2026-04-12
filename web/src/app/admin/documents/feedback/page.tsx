"use client";

import { LoadingAnimation } from "@/components/Loading";
import { useMostReactedToDocuments } from "@/lib/hooks";
import { DocumentFeedbackTable } from "./DocumentFeedbackTable";
import { numPages, numToDisplay } from "./constants";
import Title from "@/components/ui/title";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { useTranslations } from "next-intl";

const route = ADMIN_ROUTES.DOCUMENT_FEEDBACK;

function Main() {
  const t = useTranslations("admin.documents");
  const tc = useTranslations("common");
  const {
    data: mostLikedDocuments,
    isLoading: isMostLikedDocumentsLoading,
    error: mostLikedDocumentsError,
    refreshDocs: refreshMostLikedDocuments,
  } = useMostReactedToDocuments(false, numToDisplay * numPages);

  const {
    data: mostDislikedDocuments,
    isLoading: isMostLikedDocumentLoading,
    error: mostDislikedDocumentsError,
    refreshDocs: refreshMostDislikedDocuments,
  } = useMostReactedToDocuments(true, numToDisplay * numPages);

  const refresh = () => {
    refreshMostLikedDocuments();
    refreshMostDislikedDocuments();
  };

  if (isMostLikedDocumentsLoading || isMostLikedDocumentLoading) {
    return <LoadingAnimation text={tc("loading")} />;
  }

  if (
    mostLikedDocumentsError ||
    mostDislikedDocumentsError ||
    !mostLikedDocuments ||
    !mostDislikedDocuments
  ) {
    return (
      <div className="text-red-600">
        {t("errorLoadingDocuments", {
          error: mostDislikedDocumentsError || mostLikedDocumentsError,
        })}
      </div>
    );
  }

  return (
    <div>
      <Title className="mb-2">{t("mostLikedDocuments")}</Title>
      <DocumentFeedbackTable documents={mostLikedDocuments} refresh={refresh} />

      <Title className="mb-2 mt-6">{t("mostDislikedDocuments")}</Title>
      <DocumentFeedbackTable
        documents={mostDislikedDocuments}
        refresh={refresh}
      />
    </div>
  );
}

export default function Page() {
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header icon={route.icon} title={route.title} separator />
      <SettingsLayouts.Body>
        <Main />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
