"use client";
import { useTranslation } from "@/hooks/useTranslation";
import k from "./../../../../i18n/keys";

import { LoadingAnimation } from "@/components/Loading";
import { ThumbsUpIcon } from "@/components/icons/icons";
import { useMostReactedToDocuments } from "@/lib/hooks";
import { DocumentFeedbackTable } from "./DocumentFeedbackTable";
import { numPages, numToDisplay } from "./constants";
import { AdminPageTitle } from "@/components/admin/Title";
import Title from "@/components/ui/title";

const Main = () => {
  const { t } = useTranslation();
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
    return <LoadingAnimation text="Loading" />;
  }

  if (
    mostLikedDocumentsError ||
    mostDislikedDocumentsError ||
    !mostLikedDocuments ||
    !mostDislikedDocuments
  ) {
    return (
      <div className="text-red-600">
        {t(k.ERROR_LOADING_DOCUMENTS)}{" "}
        {mostDislikedDocumentsError || mostLikedDocumentsError}
      </div>
    );
  }

  return (
    <div className="mb-8">
      <Title className="mb-2">{t(k.MOST_LIKED_DOCUMENTS)}</Title>
      <DocumentFeedbackTable documents={mostLikedDocuments} refresh={refresh} />

      <Title className="mb-2 mt-6">{t(k.MOST_DISLIKED_DOCUMENTS)}</Title>
      <DocumentFeedbackTable
        documents={mostDislikedDocuments}
        refresh={refresh}
      />
    </div>
  );
};

const Page = () => {
  const { t } = useTranslation();
  return (
    <div className="container mx-auto">
      <AdminPageTitle
        icon={<ThumbsUpIcon size={32} />}
        title={t(k.DOCUMENT_FEEDBACK)}
      />

      <Main />
    </div>
  );
};

export default Page;
