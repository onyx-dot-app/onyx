"use client";

import { LoadingAnimation } from "@/components/Loading";
import { NotebookIcon } from "@/components/icons/icons";
import { CCPairIndexingStatusTable } from "./CCPairIndexingStatusTable";
import { AdminPageTitle } from "@/components/admin/Title";
import Link from "next/link";
import Text from "@/components/ui/text";
// import { useConnectorCredentialIndexingStatus } from "@/lib/hooks";
import { usePopupFromQuery } from "@/components/popup/PopupFromQuery";
import { Button } from "@/components/ui/button";
import {
  GetConnectorIndexingStatusQueryError,
  GetConnectorIndexingStatusQueryResult,
  useGetConnectorIndexingStatus,
} from "@/lib/generated/onyx-api/default/default";
import { HTTPValidationError } from "@/lib/generated/onyx-api/model";

function Main() {
  const {
    data: indexAttemptData,
    isLoading: indexAttemptIsLoading,
    error: indexAttemptError,
  } = useGetConnectorIndexingStatus<HTTPValidationError>(undefined, {
    swr: {
      refreshInterval: 30000,
    },
  });

  const {
    data: editableIndexAttemptData,
    isLoading: editableIndexAttemptIsLoading,
    error: editableIndexAttemptError,
  } = useGetConnectorIndexingStatus<HTTPValidationError>(
    { get_editable: true }, // or undefined if false
    {
      swr: {
        refreshInterval: undefined,
      },
    }
  );

  // const {
  //   data: indexAttemptData,
  //   isLoading: indexAttemptIsLoading,
  //   error: indexAttemptError,
  // } = useConnectorCredentialIndexingStatus();

  // const {
  //   data: editableIndexAttemptData,
  //   isLoading: editableIndexAttemptIsLoading,
  //   error: editableIndexAttemptError,
  // } = useConnectorCredentialIndexingStatus(undefined, true);

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
        {indexAttemptError?.detail?.[0]?.msg ||
          editableIndexAttemptError?.detail?.[0]?.msg ||
          "Error loading indexing history."}
      </div>
    );
  }

  // Handle cases where data from SWR is unexpectedly undefined
  if (!indexAttemptData || !editableIndexAttemptData) {
    return (
      <div className="text-error">
        Indexing history data is not available. This is an unexpected state.
      </div>
    );
  }

  // Handle API errors returned in the response (e.g., status 422)
  if (indexAttemptData.status !== 200) {
    const apiError = indexAttemptData.data as HTTPValidationError;
    const message =
      apiError.detail?.[0]?.msg ||
      `API error fetching primary indexing status (Status: ${indexAttemptData.status}).`;
    return <div className="text-error">{message}</div>;
  }

  if (editableIndexAttemptData.status !== 200) {
    const apiError = editableIndexAttemptData.data as HTTPValidationError;
    const message =
      apiError.detail?.[0]?.msg ||
      `API error fetching editable indexing status (Status: ${editableIndexAttemptData.status}).`;
    return <div className="text-error">{message}</div>;
  }

  // At this point, both API calls were successful (status 200)
  // indexAttemptData.data is ConnectorIndexingStatus[]
  // editableIndexAttemptData.data is ConnectorIndexingStatus[]
  const actualIndexAttempts = indexAttemptData.data; // No `as ConnectorIndexingStatus[]` needed if TS infers correctly
  const actualEditableIndexAttempts = editableIndexAttemptData.data;

  if (actualIndexAttempts.length === 0) {
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
  actualIndexAttempts.sort((a, b) => {
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
      ccPairsIndexingStatuses={actualIndexAttempts}
      editableCcPairsIndexingStatuses={actualEditableIndexAttempts}
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
