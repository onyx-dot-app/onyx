"use client";

import { BackButton } from "@/components/BackButton";
import { ErrorCallout } from "@/components/ErrorCallout";
import { ThreeDotsLoader } from "@/components/Loading";
import { FiAlertTriangle } from "react-icons/fi";
import { SourceIcon } from "@/components/SourceIcon";
import { CCPairStatus } from "@/components/Status";
import { usePopup } from "@/components/admin/connectors/Popup";
import CredentialSection from "@/components/credentials/CredentialSection";
import { CheckmarkIcon, EditIcon, XIcon } from "@/components/icons/icons";
import { updateConnectorCredentialPairName } from "@/lib/connector";
import { credentialTemplates } from "@/lib/connectors/credentials";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { ValidSources } from "@/lib/types";
import { Button, Divider, Title, Badge, Text } from "@tremor/react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import useSWR, { mutate } from "swr";
import { AdvancedConfigDisplay, ConfigDisplay } from "./ConfigDisplay";
import { DeletionButton } from "./DeletionButton";
import DeletionErrorStatus from "./DeletionErrorStatus";
import { IndexingAttemptsTable } from "./IndexingAttemptsTable";
import { ModifyStatusButtonCluster } from "./ModifyStatusButtonCluster";
import { ReIndexButton } from "./ReIndexButton";
import { buildCCPairInfoUrl } from "./lib";
import { CCPairFullInfo, ConnectorCredentialPairStatus } from "./types";

// since the uploaded files are cleaned up after some period of time
// re-indexing will not work for the file connector. Also, it would not
// make sense to re-index, since the files will not have changed.
const CONNECTOR_TYPES_THAT_CANT_REINDEX: ValidSources[] = ["file"];

function Main({ ccPairId }: { ccPairId: number }) {
  const router = useRouter(); // Initialize the router
  const {
    data: ccPair,
    isLoading,
    error,
  } = useSWR<CCPairFullInfo>(
    buildCCPairInfoUrl(ccPairId),
    errorHandlingFetcher,
    { refreshInterval: 5000 } // 5 seconds
  );

  const [hasLoadedOnce, setHasLoadedOnce] = useState(false);
  const [editableName, setEditableName] = useState(ccPair?.name || "");
  const [isEditing, setIsEditing] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const { popup, setPopup } = usePopup();

  const finishConnectorDeletion = useCallback(() => {
    router.push("/admin/indexing/status?message=connector-deleted");
  }, [router]);

  useEffect(() => {
    if (isEditing && inputRef.current) {
      inputRef.current.focus();
    }
  }, [isEditing]);

  useEffect(() => {
    if (isLoading) {
      return;
    }
    if (ccPair && !error) {
      setHasLoadedOnce(true);
    }

    if (
      (hasLoadedOnce && (error || !ccPair)) ||
      (ccPair?.status === ConnectorCredentialPairStatus.DELETING &&
        !ccPair.connector)
    ) {
      finishConnectorDeletion();
    }
  }, [isLoading, ccPair, error, hasLoadedOnce, finishConnectorDeletion]);

  const handleNameChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setEditableName(e.target.value);
  };

  const handleUpdateName = async () => {
    try {
      const response = await updateConnectorCredentialPairName(
        ccPair?.id!,
        editableName
      );
      if (!response.ok) {
        throw new Error(await response.text());
      }
      mutate(buildCCPairInfoUrl(ccPairId));
      setIsEditing(false);
      setPopup({
        message: "Connector name updated successfully",
        type: "success",
      });
    } catch (error) {
      setPopup({
        message: `Failed to update connector name`,
        type: "error",
      });
    }
  };

  if (isLoading) {
    return <ThreeDotsLoader />;
  }

  if (!ccPair || (!hasLoadedOnce && error)) {
    return (
      <ErrorCallout
        errorTitle={`Failed to fetch info on Connector with ID ${ccPairId}`}
        errorMsg={error?.info?.detail || error?.toString() || "Unknown error"}
      />
    );
  }

  const isDeleting = ccPair.status === ConnectorCredentialPairStatus.DELETING;

  const refresh = () => {
    mutate(buildCCPairInfoUrl(ccPairId));
  };

  const startEditing = () => {
    setEditableName(ccPair.name);
    setIsEditing(true);
  };

  const resetEditing = () => {
    setIsEditing(false);
    setEditableName(ccPair.name);
  };

  const {
    prune_freq: pruneFreq,
    refresh_freq: refreshFreq,
    indexing_start: indexingStart,
  } = ccPair.connector;
  return (
    <>
      {popup}
      <BackButton
        behaviorOverride={() => router.push("/admin/indexing/status")}
      />
      <div className="pb-1 flex mt-1">
        <div className="mr-2 my-auto">
          <SourceIcon iconSize={24} sourceType={ccPair.connector.source} />
        </div>

        {ccPair.is_editable_for_current_user && isEditing ? (
          <div className="flex items-center">
            <input
              ref={inputRef}
              type="text"
              value={editableName}
              onChange={handleNameChange}
              className="text-3xl w-full ring ring-1 ring-neutral-800 text-emphasis font-bold"
            />
            <Button onClick={handleUpdateName} className="ml-2">
              <CheckmarkIcon className="text-neutral-200" />
            </Button>
            <Button onClick={() => resetEditing()} className="ml-2">
              <XIcon className="text-neutral-200" />
            </Button>
          </div>
        ) : (
          <h1
            onClick={() =>
              ccPair.is_editable_for_current_user && startEditing()
            }
            className={`group flex ${ccPair.is_editable_for_current_user ? "cursor-pointer" : ""} text-3xl text-emphasis gap-x-2 items-center font-bold`}
          >
            {ccPair.name}
            {ccPair.is_editable_for_current_user && (
              <EditIcon className="group-hover:visible invisible" />
            )}
          </h1>
        )}

        {ccPair.is_editable_for_current_user && (
          <div className="ml-auto flex gap-x-2">
            {!CONNECTOR_TYPES_THAT_CANT_REINDEX.includes(
              ccPair.connector.source
            ) && (
              <ReIndexButton
                ccPairId={ccPair.id}
                connectorId={ccPair.connector.id}
                credentialId={ccPair.credential.id}
                isDisabled={
                  ccPair.indexing ||
                  ccPair.status === ConnectorCredentialPairStatus.PAUSED
                }
                isIndexing={ccPair.indexing}
                isDeleting={isDeleting}
              />
            )}
            {!isDeleting && <ModifyStatusButtonCluster ccPair={ccPair} />}
          </div>
        )}
      </div>
      <CCPairStatus
        status={ccPair.last_index_attempt_status || "not_started"}
        disabled={ccPair.status === ConnectorCredentialPairStatus.PAUSED}
        isDeleting={isDeleting}
      />
      <div className="text-sm mt-1">
        Total Documents Indexed:{" "}
        <b className="text-emphasis">{ccPair.num_docs_indexed}</b>
      </div>
      {!ccPair.is_editable_for_current_user && (
        <div className="text-sm mt-2 text-neutral-500 italic">
          {ccPair.is_public
            ? "Public connectors are not editable by curators."
            : "This connector belongs to groups where you don't have curator permissions, so it's not editable."}
        </div>
      )}

      {ccPair.deletion_failure_message &&
        ccPair.status === ConnectorCredentialPairStatus.DELETING && (
          <>
            <div className="mt-6" />
            <DeletionErrorStatus
              deletion_failure_message={ccPair.deletion_failure_message}
            />
          </>
        )}

      {credentialTemplates[ccPair.connector.source] &&
        ccPair.is_editable_for_current_user && (
          <>
            <Divider />

            <Title className="mb-2">Credentials</Title>

            <CredentialSection
              ccPair={ccPair}
              sourceType={ccPair.connector.source}
              refresh={() => refresh()}
            />
          </>
        )}
      <Divider />
      <ConfigDisplay
        connectorSpecificConfig={ccPair.connector.connector_specific_config}
        sourceType={ccPair.connector.source}
      />

      {(pruneFreq || indexingStart || refreshFreq) && (
        <AdvancedConfigDisplay
          pruneFreq={pruneFreq}
          indexingStart={indexingStart}
          refreshFreq={refreshFreq}
        />
      )}

      {/* NOTE: no divider / title here for `ConfigDisplay` since it is optional and we need
        to render these conditionally.*/}
      <div className="mt-6">
        <div className="flex">
          <Title>Indexing Attempts</Title>
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
            {ccPair.is_editable_for_current_user && (
              <DeletionButton ccPair={ccPair} />
            )}
          </div>
        </div>
      </div>
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
