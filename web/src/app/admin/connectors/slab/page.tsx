"use client";

import * as Yup from "yup";
import { SlabIcon, TrashIcon } from "@/components/icons/icons";
import { TextFormField } from "@/components/admin/connectors/Field";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import { CredentialForm } from "@/components/admin/connectors/CredentialForm";
import {
  ConnectorIndexingStatus,
  SlabCredentialJson,
  SlabConfig,
  Credential,
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
import { Card, Text, Title } from "@tremor/react";
import { AdminPageTitle } from "@/components/admin/Title";

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
    isValidating: isCredentialsValidating,
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
        errorTitle="Failed to load connectors"
        errorMsg={connectorIndexingStatusesError?.info?.detail}
      />
    );
  }

  if (credentialsError || !credentialsData) {
    return (
      <ErrorCallout
        errorTitle="Failed to load credentials"
        errorMsg={credentialsError?.info?.detail}
      />
    );
  }

  const slabConnectorIndexingStatuses: ConnectorIndexingStatus<
    SlabConfig,
    SlabCredentialJson
  >[] = connectorIndexingStatuses.filter(
    (connectorIndexingStatus) =>
      connectorIndexingStatus.connector.source === "slab"
  );
  const slabCredential: Credential<SlabCredentialJson> | undefined =
    credentialsData.find(
      (credential) => credential.credential_json?.slab_bot_token
    );

  return (
    <>
      {popup}
      <Title className="mb-2 mt-6 ml-auto mr-auto">
        Step 1: Provide your Credentials
      </Title>

      {slabCredential ? (
        <>
          <div className="flex mb-1 text-sm">
            <Text className="my-auto">Existing Slab Bot Token: </Text>
            <Text className="ml-1 italic my-auto max-w-md truncate">
              {slabCredential.credential_json?.slab_bot_token}
            </Text>
            <button
              className="ml-1 hover:bg-hover rounded p-1"
              onClick={async () => {
                if (slabConnectorIndexingStatuses.length > 0) {
                  setPopup({
                    type: "error",
                    message:
                      "Must delete all connectors before deleting credentials",
                  });
                  return;
                }
                await adminDeleteCredential(slabCredential.id);
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
            To use the Slab connector, first follow the guide{" "}
            <a
              className="text-link"
              href="https://docs.danswer.dev/connectors/slab"
              target="_blank"
            >
              here
            </a>{" "}
            to generate a Slab Bot Token.
          </Text>
          <Card className="p-6 mt-2">
            <CredentialForm<SlabCredentialJson>
              formBody={
                <>
                  <TextFormField
                    name="slab_bot_token"
                    label="Slab Bot Token:"
                    type="password"
                  />
                </>
              }
              validationSchema={Yup.object().shape({
                slab_bot_token: Yup.string().required(
                  "Please enter your Slab Bot Token"
                ),
              })}
              initialValues={{
                slab_bot_token: "",
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
        Step 2: What&apos;s the base URL for your Slab team?
      </Title>
      {slabCredential ? (
        <>
          {slabConnectorIndexingStatuses.length > 0 ? (
            <>
              <Text className="mb-2">
                We are pulling the latest documents from{" "}
                <a
                  href={
                    slabConnectorIndexingStatuses[0].connector
                      .connector_specific_config.base_url
                  }
                  className="text-blue-600"
                >
                  {
                    slabConnectorIndexingStatuses[0].connector
                      .connector_specific_config.base_url
                  }
                </a>{" "}
                every <b>10</b> minutes.
              </Text>
              <ConnectorsTable<SlabConfig, SlabCredentialJson>
                connectorIndexingStatuses={slabConnectorIndexingStatuses}
                liveCredential={slabCredential}
                getCredential={(credential) => {
                  return (
                    <div>
                      <p>{credential.credential_json.slab_bot_token}</p>
                    </div>
                  );
                }}
                onCredentialLink={async (connectorId) => {
                  if (slabCredential) {
                    await linkCredential(connectorId, slabCredential.id);
                    mutate("/api/manage/admin/connector/indexing-status");
                  }
                }}
                specialColumns={[
                  {
                    header: "Url",
                    key: "url",
                    getValue: (ccPairStatus) => {
                      const connectorConfig =
                        ccPairStatus.connector.connector_specific_config;
                      return (
                        <a
                          className="text-blue-500"
                          href={connectorConfig.base_url}
                        >
                          {connectorConfig.base_url}
                        </a>
                      );
                    },
                  },
                ]}
                onUpdate={() =>
                  mutate("/api/manage/admin/connector/indexing-status")
                }
              />
            </>
          ) : (
            <>
              <Text className="mb-4">
                Specify the base URL for your Slab team below. This will look
                something like:{" "}
                <b>
                  <i>https://danswer.slab.com/</i>
                </b>
              </Text>
              <Card className="mt-4">
                <h2 className="font-bold mb-3">Add a New Space</h2>
                <ConnectorForm<SlabConfig>
                  nameBuilder={(values) => `SlabConnector-${values.base_url}`}
                  ccPairNameBuilder={(values) => values.base_url}
                  source="slab"
                  inputType="poll"
                  formBody={
                    <>
                      <TextFormField name="base_url" label="Base URL:" />
                    </>
                  }
                  validationSchema={Yup.object().shape({
                    base_url: Yup.string().required(
                      "Please enter the base URL for your team e.g. https://danswer.slab.com/"
                    ),
                  })}
                  initialValues={{
                    base_url: "",
                  }}
                  refreshFreq={10 * 60} // 10 minutes
                  credentialId={slabCredential.id}
                />
              </Card>
            </>
          )}
        </>
      ) : (
        <>
          <Text>
            Please provide your access token in Step 1 first! Once done with
            that, you can then specify the URL for your Slab team and get
            started with indexing.
          </Text>
        </>
      )}
    </>
  );
};

export default function Page() {
  return (
    <div className="mx-auto container">
      <AdminPageTitle icon={<SlabIcon size={32} />} title="Slab" />

      <Main />
    </div>
  );
}
