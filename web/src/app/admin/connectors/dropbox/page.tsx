"use client";

import { AdminPageTitle } from "@/components/admin/Title";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import { DropboxIcon } from "@/components/icons/icons";
import { LoadingAnimation } from "@/components/Loading";
import { ConnectorForm } from "@/components/admin/connectors/ConnectorForm";
import { CredentialForm } from "@/components/admin/connectors/CredentialForm";
import { TextFormField } from "@/components/admin/connectors/Field";
import { usePopup } from "@/components/admin/connectors/Popup";
import { ConnectorsTable } from "@/components/admin/connectors/table/ConnectorsTable";
import { TrashIcon } from "@/components/icons/icons";
import { adminDeleteCredential, linkCredential } from "@/lib/credential";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { ErrorCallout } from "@/components/ErrorCallout";
import { usePublicCredentials } from "@/lib/hooks";
import {
  ConnectorIndexingStatus,
  Credential,
  DropboxConfig,
  DropboxCredentialJson,
} from "@/lib/types";
import { Card, Text, Title } from "@tremor/react";
import useSWR, { useSWRConfig } from "swr";
import * as Yup from "yup";

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

  const dropboxConnectorIndexingStatuses: ConnectorIndexingStatus<
    DropboxConfig,
    DropboxCredentialJson
  >[] = connectorIndexingStatuses.filter(
    (connectorIndexingStatus) =>
      connectorIndexingStatus.connector.source === "dropbox"
  );
  const dropboxCredential: Credential<DropboxCredentialJson> | undefined =
    credentialsData.find(
      (credential) => credential.credential_json?.dropbox_access_token
    );

  return (
    <>
      {popup}
      <Title className="mb-2 mt-6 ml-auto mr-auto">
        Provide your API details
      </Title>

      {dropboxCredential ? (
        <>
          <div className="flex mb-1 text-sm">
            <p className="my-auto">Existing API Token: </p>
            <p className="ml-1 italic my-auto max-w-md">
              {dropboxCredential.credential_json?.dropbox_access_token}
            </p>
            <button
              className="ml-1 hover:bg-hover rounded p-1"
              onClick={async () => {
                if (dropboxConnectorIndexingStatuses.length > 0) {
                  setPopup({
                    type: "error",
                    message:
                      "Must delete all connectors before deleting credentials",
                  });
                  return;
                }
                await adminDeleteCredential(dropboxCredential.id);
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
            See the Dropbox connector{" "}
            <a
              className="text-blue-500"
              href="https://docs.danswer.dev/connectors/dropbox/overview"
            >
              setup guide
            </a>{" "}
            on the Danswer docs to obtain a Dropbox token.
          </Text>
          <Card className="mt-4 mb-4">
            <CredentialForm<DropboxCredentialJson>
              formBody={
                <>
                  <TextFormField
                    name="dropbox_access_token"
                    label="Dropbox API Token:"
                    type="password"
                  />
                </>
              }
              validationSchema={Yup.object().shape({
                dropbox_access_token: Yup.string().required(
                  "Please enter your Dropbox API token"
                ),
              })}
              initialValues={{
                dropbox_access_token: "",
              }}
              onSubmit={(isSuccess) => {
                if (isSuccess) {
                  refreshCredentials();
                  mutate("/api/manage/admin/connector/indexing-status");
                }
              }}
            />
          </Card>
        </>
      )}

      {dropboxConnectorIndexingStatuses.length > 0 && (
        <>
          <Title className="mb-2 mt-6 ml-auto mr-auto">
            Dropbox indexing status
          </Title>
          <Text className="mb-2">
            Due to Dropbox access key design, the Dropbox connector will only
            re-index files after a new access key is provided and the indexing
            process is re-run manually. Check the docs for more information.
          </Text>
          <div className="mb-2">
            <ConnectorsTable<DropboxConfig, DropboxCredentialJson>
              connectorIndexingStatuses={dropboxConnectorIndexingStatuses}
              liveCredential={dropboxCredential}
              onCredentialLink={async (connectorId) => {
                if (dropboxCredential) {
                  await linkCredential(connectorId, dropboxCredential.id);
                  mutate("/api/manage/admin/connector/indexing-status");
                }
              }}
              onUpdate={() =>
                mutate("/api/manage/admin/connector/indexing-status")
              }
            />
          </div>
        </>
      )}

      {dropboxCredential && dropboxConnectorIndexingStatuses.length === 0 && (
        <>
          <Card className="mt-4">
            <h2 className="font-bold mb-3">Create Connection</h2>
            <p className="text-sm mb-4">
              Press connect below to start the connection to your Dropbox
              instance.
            </p>
            <ConnectorForm<DropboxConfig>
              nameBuilder={(values) => `Dropbox`}
              ccPairNameBuilder={(values) => `Dropbox`}
              source="dropbox"
              inputType="poll"
              formBody={<></>}
              validationSchema={Yup.object().shape({})}
              initialValues={{}}
              // refreshFreq={10 * 60} // disabled re-indexing
              credentialId={dropboxCredential.id}
            />
          </Card>
        </>
      )}
    </>
  );
};

export default function Page() {
  return (
    <div className="mx-auto container">
      {" "}
      <AdminPageTitle icon={<DropboxIcon size={32} />} title="Dropbox" />
      <Main />
    </div>
  );
}
