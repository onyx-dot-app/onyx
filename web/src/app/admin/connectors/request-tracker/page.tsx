"use client";

import * as Yup from "yup";
import { TrashIcon, RequestTrackerIcon } from "@/components/icons/icons"; // Make sure you have a Document360 icon
import { errorHandlingFetcher } from "@/lib/fetcher";
import { ErrorCallout } from "@/components/ErrorCallout";
import useSWR, { useSWRConfig } from "swr";
import { LoadingAnimation } from "@/components/Loading";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import {
  RequestTrackerConfig,
  RequestTrackerCredentialJson,
  ConnectorIndexingStatus,
  Credential,
} from "@/lib/types"; // Modify or create these types as required
import { adminDeleteCredential, linkCredential } from "@/lib/credential";
import { CredentialForm } from "@/components/admin/connectors/CredentialForm";
import {
  TextFormField,
  TextArrayFieldBuilder,
} from "@/components/admin/connectors/Field";
import { ConnectorsTable } from "@/components/admin/connectors/table/ConnectorsTable";
import { ConnectorForm } from "@/components/admin/connectors/ConnectorForm";
import { usePublicCredentials } from "@/lib/hooks";
import { AdminPageTitle } from "@/components/admin/Title";
import { Card, Text, Title } from "@tremor/react";

const MainSection = () => {
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
    error: credentialsError,
    refreshCredentials,
  } = usePublicCredentials();

  if (
    (!connectorIndexingStatuses && isConnectorIndexingStatusesLoading) ||
    (!credentialsData && isCredentialsLoading)
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

  const requestTrackerConnectorIndexingStatuses: ConnectorIndexingStatus<
    RequestTrackerConfig,
    RequestTrackerCredentialJson
  >[] = connectorIndexingStatuses.filter(
    (connectorIndexingStatus) =>
      connectorIndexingStatus.connector.source === "requesttracker"
  );

  const requestTrackerCredential:
    | Credential<RequestTrackerCredentialJson>
    | undefined = credentialsData.find(
    (credential) => credential.credential_json?.requesttracker_username
  );

  return (
    <>
      <Title className="mb-2 mt-6 ml-auto mr-auto">
        Step 1: Provide Request Tracker credentials
      </Title>
      {requestTrackerCredential ? (
        <>
          <div className="flex mb-1 text-sm">
            <Text className="my-auto">Existing Request Tracker username: </Text>
            <Text className="ml-1 italic my-auto">
              {requestTrackerCredential.credential_json.requesttracker_username}
            </Text>
            <button
              className="ml-1 hover:bg-hover rounded p-1"
              onClick={async () => {
                await adminDeleteCredential(requestTrackerCredential.id);
                refreshCredentials();
              }}
            >
              <TrashIcon />
            </button>
          </div>
        </>
      ) : (
        <>
          <Text className="mb-2">
            To use the Request Tracker connector, provide a Request Tracker
            username, password, and base url.
          </Text>
          <Text className="mb-2">
            This connector currently supports{" "}
            <a
              className="text-link"
              href="https://rt-wiki.bestpractical.com/wiki/REST"
              target="_blank"
            >
              Request Tracker REST API 1.0
            </a>
            ,{" "}
            <b>not the latest REST API 2.0 introduced in Request Tracker 5.0</b>
            .
          </Text>
          <Card className="mt-2">
            <CredentialForm<RequestTrackerCredentialJson>
              formBody={
                <>
                  <TextFormField
                    name="requesttracker_username"
                    label="Request Tracker username:"
                  />
                  <TextFormField
                    name="requesttracker_password"
                    label="Request Tracker password:"
                    type="password"
                  />
                  <TextFormField
                    name="requesttracker_base_url"
                    label="Request Tracker base url:"
                  />
                </>
              }
              validationSchema={Yup.object().shape({
                requesttracker_username: Yup.string().required(
                  "Please enter your Request Tracker username"
                ),
                requesttracker_password: Yup.string().required(
                  "Please enter your Request Tracker password"
                ),
                requesttracker_base_url: Yup.string()
                  .url()
                  .required(
                    "Please enter the base url of your RT installation"
                  ),
              })}
              initialValues={{
                requesttracker_username: "",
                requesttracker_password: "",
                requesttracker_base_url: "",
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
        Step 2: Manage Request Tracker Connector
      </Title>

      {requestTrackerConnectorIndexingStatuses.length > 0 && (
        <>
          <Text className="mb-2">
            We index the most recently updated tickets from each Request Tracker
            instance listed below regularly.
          </Text>
          <Text className="mb-2">
            The initial poll at this time retrieves tickets updated in the past
            hour. All subsequent polls execute every ten minutes. This should be
            configurable in the future.
          </Text>
          <div className="mb-2">
            <ConnectorsTable<RequestTrackerConfig, RequestTrackerCredentialJson>
              connectorIndexingStatuses={
                requestTrackerConnectorIndexingStatuses
              }
              liveCredential={requestTrackerCredential}
              getCredential={(credential) =>
                credential.credential_json.requesttracker_base_url
              }
              onUpdate={() =>
                mutate("/api/manage/admin/connector/indexing-status")
              }
              onCredentialLink={async (connectorId) => {
                if (requestTrackerCredential) {
                  await linkCredential(
                    connectorId,
                    requestTrackerCredential.id
                  );
                  mutate("/api/manage/admin/connector/indexing-status");
                }
              }}
            />
          </div>
        </>
      )}

      {requestTrackerCredential &&
      requestTrackerConnectorIndexingStatuses.length === 0 ? (
        <Card className="mt-4">
          <ConnectorForm<RequestTrackerConfig>
            nameBuilder={(values) =>
              `RequestTracker-${requestTrackerCredential.credential_json.requesttracker_base_url}`
            }
            ccPairNameBuilder={(values) =>
              `Request Tracker ${requestTrackerCredential.credential_json.requesttracker_base_url}`
            }
            source="requesttracker"
            inputType="poll"
            validationSchema={Yup.object().shape({})}
            formBody={<></>}
            initialValues={{}}
            credentialId={requestTrackerCredential.id}
            refreshFreq={10 * 60} // 10 minutes
          />
        </Card>
      ) : (
        <></>
      )}
    </>
  );
};

export default function Page() {
  return (
    <div className="mx-auto container">
      <AdminPageTitle
        icon={<RequestTrackerIcon size={32} />}
        title="Request Tracker"
      />

      <MainSection />
    </div>
  );
}
