"use client";
import { useTranslation } from "@/hooks/useTranslation";
import k from "./../../../../i18n/keys";

import { LoadingAnimation } from "@/components/Loading";
import { NotebookIcon } from "@/components/icons/icons";
import { CCPairIndexingStatusTable } from "./CCPairIndexingStatusTable";
import { AdminPageTitle } from "@/components/admin/Title";
import Link from "next/link";
import Text from "@/components/ui/text";
import { useConnectorCredentialIndexingStatus } from "@/lib/hooks";
import { usePopupFromQuery } from "@/components/popup/PopupFromQuery";
import { Button } from "@/components/ui/button";

function Main() {
  const { t } = useTranslation();
  const {
    data: indexAttemptData,
    isLoading: indexAttemptIsLoading,
    error: indexAttemptError,
  } = useConnectorCredentialIndexingStatus();

  const {
    data: editableIndexAttemptData,
    isLoading: editableIndexAttemptIsLoading,
    error: editableIndexAttemptError,
  } = useConnectorCredentialIndexingStatus(undefined, true);

  if (indexAttemptIsLoading || editableIndexAttemptIsLoading) {
    return <LoadingAnimation text="" />;
  }

  if (
    indexAttemptError ||
    !indexAttemptData ||
    editableIndexAttemptError ||
    !editableIndexAttemptData
  ) {
    return (
      <div className="text-error">
        {indexAttemptError?.info?.detail ||
          editableIndexAttemptError?.info?.detail ||
          t(k.INDEXING_HISTORY_ERROR)}
      </div>
    );
  }

  if (indexAttemptData.length === 0) {
    return (
      <Text>
        {t(k.IT_LOOKS_LIKE_YOU_DON_T_HAVE_A)}{" "}
        <Link className="text-link" href="/admin/add-connector">
          {t(k.ADD_CONNECTOR)}
        </Link>{" "}
        {t(k.PAGE_TO_GET_STARTED)}
      </Text>
    );
  }

  // sort by source name
  indexAttemptData.sort((a, b) => {
    if (a.connector.source < b.connector.source) {
      return -1;
    } else if (a.connector.source > b.connector.source) {
      return 1;
    } else {
      return 0;
    }
  });

  return (
    <CCPairIndexingStatusTable
      ccPairsIndexingStatuses={indexAttemptData}
      editableCcPairsIndexingStatuses={editableIndexAttemptData}
    />
  );
}

export default function Status() {
  const { t } = useTranslation();
  const { popup } = usePopupFromQuery({
    "connector-created": {
      message: t(k.CONNECTOR_CREATED_SUCCESS),
      type: "success",
    },
    "connector-deleted": {
      message: t(k.CONNECTOR_DELETED_SUCCESS),
      type: "success",
    },
  });

  return (
    <div className="mx-auto container">
      {popup}
      <AdminPageTitle
        icon={<NotebookIcon size={32} />}
        title={t(k.EXISTING_CONNECTORS)}
        farRightElement={
          <Link href="/admin/add-connector">
            <Button variant="success-reverse">{t(k.ADD_CONNECTOR)}</Button>
          </Link>
        }
      />

      <Main />
    </div>
  );
}
