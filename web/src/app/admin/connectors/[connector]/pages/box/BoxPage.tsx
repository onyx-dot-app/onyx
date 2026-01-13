"use client";

import React from "react";
import { ErrorCallout } from "@/components/ErrorCallout";
import { LoadingAnimation } from "@/components/Loading";
import { usePopup } from "@/components/admin/connectors/Popup";
import { CCPairBasicInfo, ValidSources } from "@/lib/types";
import { Credential, BoxCredentialJson } from "@/lib/connectors/credentials";
import { BoxAuthSection, BoxJsonUploadSection } from "./Credential";
import { usePublicCredentials, useBasicConnectorStatus } from "@/lib/hooks";
import Title from "@/components/ui/title";
import { useUser } from "@/components/user/UserProvider";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { buildSimilarCredentialInfoURL } from "@/app/admin/connector/[ccPairId]/lib";

export const BoxMain = () => {
  const { isAdmin, user } = useUser();
  const { popup, setPopup } = usePopup();

  const {
    data: jwtConfigData,
    isLoading: isJwtConfigLoading,
    error: isJwtConfigError,
  } = useSWR<{ client_id: string; enterprise_id: string }>(
    "/api/manage/admin/connector/box/jwt-config",
    errorHandlingFetcher
  );

  const {
    data: connectorIndexingStatuses,
    isLoading: isConnectorIndexingStatusesLoading,
    error: connectorIndexingStatusesError,
  } = useBasicConnectorStatus();

  const {
    data: credentialsData,
    isLoading: isCredentialsLoading,
    error: credentialsError,
    refreshCredentials,
  } = usePublicCredentials();

  const {
    data: boxCredentials,
    isLoading: isBoxCredentialsLoading,
    error: boxCredentialsError,
  } = useSWR<Credential<BoxCredentialJson>[]>(
    buildSimilarCredentialInfoURL(ValidSources.Box),
    errorHandlingFetcher
  );

  const handleRefresh = () => {
    refreshCredentials();
  };

  if (
    (!jwtConfigData && isJwtConfigLoading && !isJwtConfigError) ||
    (!connectorIndexingStatuses && isConnectorIndexingStatusesLoading) ||
    (!credentialsData && isCredentialsLoading) ||
    (!boxCredentials && isBoxCredentialsLoading)
  ) {
    return (
      <div className="mx-auto">
        <LoadingAnimation text="" />
      </div>
    );
  }

  if (isJwtConfigError) {
    return <ErrorCallout errorTitle="Failed to load Box JWT config." />;
  }

  if (credentialsError || !credentialsData) {
    return <ErrorCallout errorTitle="Failed to load credentials." />;
  }

  if (boxCredentialsError) {
    return <ErrorCallout errorTitle="Failed to load Box credentials." />;
  }

  if (connectorIndexingStatusesError || !connectorIndexingStatuses) {
    return <ErrorCallout errorTitle="Failed to load connectors." />;
  }

  const boxJwtCredential: Credential<BoxCredentialJson> | undefined =
    credentialsData.find(
      (credential) =>
        credential.credential_json?.box_jwt_config &&
        credential.source === "box"
    );

  const boxConnectorIndexingStatuses: CCPairBasicInfo[] =
    connectorIndexingStatuses.filter(
      (connectorIndexingStatus) => connectorIndexingStatus.source === "box"
    );

  const connectorExists = boxConnectorIndexingStatuses.length > 0;

  const hasUploadedJwtConfig = Boolean(jwtConfigData?.client_id);

  return (
    <>
      {popup}
      <Title className="mb-2 mt-6 ml-auto mr-auto">
        Step 1: Provide your Box JWT Config
      </Title>
      <BoxJsonUploadSection
        setPopup={setPopup}
        jwtConfigData={jwtConfigData}
        isAdmin={isAdmin}
        onSuccess={handleRefresh}
        existingAuthCredential={Boolean(boxJwtCredential)}
      />

      {isAdmin && hasUploadedJwtConfig && (
        <>
          <Title className="mb-2 mt-6 ml-auto mr-auto">
            Step 2: Create Credential
          </Title>
          <BoxAuthSection
            setPopup={setPopup}
            refreshCredentials={handleRefresh}
            boxJwtCredential={boxJwtCredential}
            jwtConfigData={jwtConfigData}
            connectorAssociated={connectorExists}
            user={user}
          />
        </>
      )}
    </>
  );
};
