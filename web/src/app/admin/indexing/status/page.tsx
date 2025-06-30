"use client";

import { LoadingAnimation } from "@/components/Loading";
import { NotebookIcon } from "@/components/icons/icons";
import { CCPairIndexingStatusTable } from "./CCPairIndexingStatusTable";
import { AdminPageTitle } from "@/components/admin/Title";
import Link from "next/link";
import Text from "@/components/ui/text";
import {
  useConnectorCredentialIndexingStatus,
  useFederatedConnectors,
} from "@/lib/hooks";
import { usePopupFromQuery } from "@/components/popup/PopupFromQuery";
import { Button } from "@/components/ui/button";

function Main() {
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

  const {
    data: federatedConnectorsData,
    isLoading: federatedConnectorsIsLoading,
    error: federatedConnectorsError,
  } = useFederatedConnectors();

  // Debug logging
  console.log("Federated connectors data:", federatedConnectorsData);
  console.log("Federated connectors error:", federatedConnectorsError);
  console.log("Federated connectors loading:", federatedConnectorsIsLoading);

  if (
    indexAttemptIsLoading ||
    editableIndexAttemptIsLoading ||
    federatedConnectorsIsLoading
  ) {
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
          "Error loading indexing history."}
      </div>
    );
  }

  if (
    indexAttemptData.length === 0 &&
    (!federatedConnectorsData || federatedConnectorsData.length === 0)
  ) {
    return (
      <Text>
        It looks like you don&apos;t have any connectors setup yet. Visit the{" "}
        <Link className="text-link" href="/admin/add-connector">
          Add Connector
        </Link>{" "}
        page to get started!
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
      federatedConnectors={federatedConnectorsData || []}
    />
  );
}

export default function Status() {
  const { popup } = usePopupFromQuery({
    "connector-created": {
      message: "Connector created successfully",
      type: "success",
    },
    "connector-deleted": {
      message: "Connector deleted successfully",
      type: "success",
    },
  });

  return (
    <div className="mx-auto container">
      {popup}
      <AdminPageTitle
        icon={<NotebookIcon size={32} />}
        title="Existing Connectors"
        farRightElement={
          <Link href="/admin/add-connector">
            <Button variant="success-reverse">Add Connector</Button>
          </Link>
        }
      />

      <Main />
    </div>
  );
}
