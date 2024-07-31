"use client";

import { CCPairFullInfo } from "./types";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import { CCPairStatus } from "@/components/Status";
import { BackButton } from "@/components/BackButton";
import { Divider, Title, Badge } from "@tremor/react";
import { IndexingAttemptsTable } from "./IndexingAttemptsTable";
import { Text } from "@tremor/react";
import { ConfigDisplay } from "./ConfigDisplay";
import { ModifyStatusButtonCluster } from "./ModifyStatusButtonCluster";
import { DeletionButton } from "./DeletionButton";
import { ErrorCallout } from "@/components/ErrorCallout";
import { ReIndexButton } from "./ReIndexButton";
import { isCurrentlyDeleting } from "@/lib/documentDeletion";
import { ValidSources } from "@/lib/types";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { ThreeDotsLoader } from "@/components/Loading";
import { buildCCPairInfoUrl } from "./lib";
import {
  FiAlertTriangle,
  FiCheckCircle,
  FiClock,
  FiPauseCircle,
} from "react-icons/fi";

// since the uploaded files are cleaned up after some period of time
// re-indexing will not work for the file connector. Also, it would not
// make sense to re-index, since the files will not have changed.
const CONNECTOR_TYPES_THAT_CANT_REINDEX: ValidSources[] = ["file"];

function Main({ ccPairId }: { ccPairId: number }) {
  const {
    data: ccPair,
    isLoading,
    error,
  } = useSWR<CCPairFullInfo>(
    buildCCPairInfoUrl(ccPairId),
    errorHandlingFetcher,
    { refreshInterval: 5000 } // 5 seconds
  );

  if (isLoading) {
    return <ThreeDotsLoader />;
  }

  if (error || !ccPair) {
    return (
      <ErrorCallout
        errorTitle={`Failed to fetch info on Connector with ID ${ccPairId}`}
        errorMsg={error?.info?.detail || error.toString()}
      />
    );
  }

  const lastIndexAttempt = ccPair.index_attempts[0];
  const isDeleting = isCurrentlyDeleting(ccPair.latest_deletion_attempt);

  // figure out if we need to artificially deflate the number of docs indexed.
  // This is required since the total number of docs indexed by a CC Pair is
  // updated before the new docs for an indexing attempt. If we don't do this,
  // there is a mismatch between these two numbers which may confuse users.
  const totalDocsIndexed =
    lastIndexAttempt?.status === "in_progress" &&
    ccPair.index_attempts.length === 1
      ? lastIndexAttempt.total_docs_indexed
      : ccPair.num_docs_indexed;

  return (
    <>
      <BackButton />
      <div className="pb-1 flex mt-1">
        <h1 className="text-3xl text-emphasis font-bold">{ccPair.name}</h1>

        <div className="ml-auto">
          <ModifyStatusButtonCluster ccPair={ccPair} />
        </div>
      </div>

      <CCPairStatus
        status={lastIndexAttempt?.status || "not_started"}
        disabled={ccPair.connector.disabled}
        isDeleting={isDeleting}
      />

      <div className="text-sm mt-1">
        Total Documents Indexed:{" "}
        <b className="text-emphasis">{totalDocsIndexed}</b>
      </div>

      <Divider />

      <ConfigDisplay
        connectorSpecificConfig={ccPair.connector.connector_specific_config}
        sourceType={ccPair.connector.source}
      />
      {/* NOTE: no divider / title here for `ConfigDisplay` since it is optional and we need
        to render these conditionally.*/}

      <div className="mt-6">
        <div className="flex">
          <Title>Indexing Attempts</Title>

          {!CONNECTOR_TYPES_THAT_CANT_REINDEX.includes(
            ccPair.connector.source
          ) && (
            <ReIndexButton
              ccPairId={ccPair.id}
              connectorId={ccPair.connector.id}
              credentialId={ccPair.credential.id}
              isDisabled={ccPair.connector.disabled}
            />
          )}
        </div>

        <IndexingAttemptsTable ccPair={ccPair} />
      </div>

      <Divider />

      <div className="mt-4">
        <Title>Delete Connector</Title>
        <Text>
          Deleting the connector will also delete all associated documents.
        </Text>

      <br/>
      {isDeleting && (
        <>
          <Badge size="md" color="yellow" icon={FiAlertTriangle}>
            Attention
          </Badge>

          <Text>
            If the deletion of the connector is stuck, you can try to delete it again.
            <br/>
            You can tell it&apos;s stuck, if the number of <b>Total Documents Indexed</b> is not decreasing, or it&apos;s 0 for a long time, and the connector is still not deleted.
          </Text>

        </>
      )}

        <div className="flex mt-16">
          <div className="mx-auto">
            <DeletionButton ccPair={ccPair} />
          </div>
        </div>
      </div>

      {/* TODO: add document search*/}
    </>
  );
}

export default function Page({ params }: { params: { ccPairId: string } }) {
  const ccPairId = parseInt(params.ccPairId);

  return (
    <div className="mx-auto container">
      <Main ccPairId={ccPairId} />
    </div>
  );
}
