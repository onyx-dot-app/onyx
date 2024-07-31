"use client";

import * as Yup from "yup";
import { HubSpotIcon, TrashIcon } from "@/components/icons/icons";
import { TextFormField } from "@/components/admin/connectors/Field";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import { CredentialForm } from "@/components/admin/connectors/CredentialForm";
import {
  Credential,
  ConnectorIndexingStatus,
  HubSpotConfig,
  HubSpotCredentialJson,
} from "@/lib/types";
import useSWR, { useSWRConfig } from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { ErrorCallout } from "@/components/ErrorCallout";
import { LoadingAnimation } from "@/components/Loading";
import { adminDeleteCredential, linkCredential } from "@/lib/credential";
import { ConnectorForm } from "@/components/admin/connectors/ConnectorForm";
import { ConnectorsTable } from "@/components/admin/connectors/table/ConnectorsTable";
import { usePopup } from "@/components/admin/connectors/Popup";
import { usePublicCredentials } from "@/lib/hooks";
import { AdminPageTitle } from "@/components/admin/Title";
import { Card, Text, Title } from "@tremor/react";

const Main = () => {
  const { popup, setPopup } = usePopup();

  const { mutate } = useSWRConfig();
  const {
    data: connectorIndexingStatuses,
    isLoading: isConnectorIndexingStatusesLoading,
    error: connectorIndexingStatusesError,
  } = useSWR<ConnectorIndexingStatus<any, any>[]>(
    "/api/manage/admin/connector/indexing-status",
    errorHandlingFetcher
  );

  const {
    data: credentialsData,
    isLoading: isCredentialsLoading,
    isValidating: isCredentialsValidating,
    error: credentialsError,
    refreshCredentials,
  } = usePublicCredentials();

  if (
    isConnectorIndexingStatusesLoading ||
    isCredentialsLoading ||
    isCredentialsValidating
  ) {
    return <LoadingAnimation text="Loading" />;
  }

  if (connectorIndexingStatusesError || !connectorIndexingStatuses) {
    return (
      <ErrorCallout
        errorTitle="Something went wrong :("
        errorMsg={connectorIndexingStatusesError?.info?.detail}
      />
    );
  }

  if (credentialsError || !credentialsData) {
    return (
      <ErrorCallout
        errorTitle="Something went wrong :("
        errorMsg={credentialsError?.info?.detail}
      />
    );
  }

  const hubSpotConnectorIndexingStatuses: ConnectorIndexingStatus<
    HubSpotConfig,
    HubSpotCredentialJson
  >[] = connectorIndexingStatuses.filter(
    (connectorIndexingStatus) =>
      connectorIndexingStatus.connector.source === "hubspot"
  );
  const hubSpotCredential: Credential<HubSpotCredentialJson> =
    credentialsData.filter(
      (credential) => credential.credential_json?.hubspot_access_token
    )[0];

  return (
    <>
      {popup}
      <Text>
        This connector allows you to sync all your HubSpot Tickets into Danswer.
      </Text>

      <Title className="mb-2 mt-6 ml-auto mr-auto">
        Step 1: Provide your Credentials
      </Title>

      {hubSpotCredential ? (
        <>
          <div className="flex mb-1 text-sm">
            <Text className="my-auto">Existing Access Token: </Text>
            <Text className="ml-1 italic my-auto max-w-md truncate">
              {hubSpotCredential.credential_json?.hubspot_access_token}
            </Text>
            <button
              className="ml-1 hover:bg-hover rounded p-1"
              onClick={async () => {
                if (hubSpotConnectorIndexingStatuses.length > 0) {
                  setPopup({
                    type: "error",
                    message:
                      "Must delete all connectors before deleting credentials",
                  });
                  return;
                }
                await adminDeleteCredential(hubSpotCredential.id);
                refreshCredentials();
              }}
            >
              <TrashIcon />
            </button>
          </div>
        </>
      ) : (
        <>
          <Text>
            To use the HubSpot connector, provide the HubSpot Access Token.
          </Text>
          <Card className="mt-4">
            <CredentialForm<HubSpotCredentialJson>
              formBody={
                <>
                  <TextFormField
                    name="hubspot_access_token"
                    label="HubSpot Access Token:"
                    type="password"
                  />
                </>
              }
              validationSchema={Yup.object().shape({
                hubspot_access_token: Yup.string().required(
                  "Please enter your HubSpot Access Token"
                ),
              })}
              initialValues={{
                hubspot_access_token: "",
              }}
              onSubmit={(isSuccess) => {
                if (isSuccess) {
                  refreshCredentials();
                }
              }}
            />
          </Card>
        </>
      )}

      <Title className="mb-2 mt-6 ml-auto mr-auto">
        Step 2: Start indexing!
      </Title>
      {hubSpotCredential ? (
        !hubSpotConnectorIndexingStatuses.length ? (
          <>
            <Text className="mb-2">
              Click the button below to start indexing! We will pull the latest
              tickets from HubSpot every <b>10</b> minutes.
            </Text>
            <div className="flex">
              <ConnectorForm<HubSpotConfig>
                nameBuilder={() => "HubSpotConnector"}
                ccPairNameBuilder={() => "HubSpotConnector"}
                source="hubspot"
                inputType="poll"
                formBody={null}
                validationSchema={Yup.object().shape({})}
                initialValues={{}}
                refreshFreq={10 * 60} // 10 minutes
                credentialId={hubSpotCredential.id}
              />
            </div>
          </>
        ) : (
          <>
            <Text className="mb-2">
              HubSpot connector is setup! We are pulling the latest tickets from
              HubSpot every <b>10</b> minutes.
            </Text>
            <ConnectorsTable<HubSpotConfig, HubSpotCredentialJson>
              connectorIndexingStatuses={hubSpotConnectorIndexingStatuses}
              liveCredential={hubSpotCredential}
              getCredential={(credential) => {
                return (
                  <div>
                    <p>{credential.credential_json.hubspot_access_token}</p>
                  </div>
                );
              }}
              onCredentialLink={async (connectorId) => {
                if (hubSpotCredential) {
                  await linkCredential(connectorId, hubSpotCredential.id);
                  mutate("/api/manage/admin/connector/indexing-status");
                }
              }}
              onUpdate={() =>
                mutate("/api/manage/admin/connector/indexing-status")
              }
            />
          </>
        )
      ) : (
        <>
          <Text>
            Please provide your access token in Step 1 first! Once done with
            that, you can then start indexing all your HubSpot tickets.
          </Text>
        </>
      )}
    </>
  );
};

export default function Page() {
  return (
    <div className="mx-auto container">
      <AdminPageTitle icon={<HubSpotIcon size={32} />} title="HubSpot" />

      <Main />
    </div>
  );
}
