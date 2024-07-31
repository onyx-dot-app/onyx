"use client";

import * as Yup from "yup";
import { ZulipIcon, TrashIcon } from "@/components/icons/icons";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { ErrorCallout } from "@/components/ErrorCallout";
import useSWR, { useSWRConfig } from "swr";
import { LoadingAnimation } from "@/components/Loading";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import {
  ZulipConfig,
  Credential,
  ZulipCredentialJson,
  ConnectorIndexingStatus,
} from "@/lib/types";
import { adminDeleteCredential, linkCredential } from "@/lib/credential";
import { CredentialForm } from "@/components/admin/connectors/CredentialForm";
import { TextFormField } from "@/components/admin/connectors/Field";
import { ConnectorsTable } from "@/components/admin/connectors/table/ConnectorsTable";
import { ConnectorForm } from "@/components/admin/connectors/ConnectorForm";
import { usePublicCredentials } from "@/lib/hooks";
import { Card, Divider, Text, Title } from "@tremor/react";
import { AdminPageTitle } from "@/components/admin/Title";

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

  const zulipConnectorIndexingStatuses: ConnectorIndexingStatus<
    ZulipConfig,
    ZulipCredentialJson
  >[] = connectorIndexingStatuses.filter(
    (connectorIndexingStatus) =>
      connectorIndexingStatus.connector.source === "zulip"
  );
  const zulipCredential: Credential<ZulipCredentialJson> | undefined =
    credentialsData.filter(
      (credential) => credential.credential_json?.zuliprc_content
    )[0];

  return (
    <>
      <Title className="mb-2 mt-6 ml-auto mr-auto">
        Step 1: Provide Credentials
      </Title>
      {zulipCredential ? (
        <>
          <div className="flex mb-1 text-sm">
            <Text className="my-auto">Existing zuliprc file content: </Text>
            <Text className="ml-1 italic my-auto">
              {zulipCredential.credential_json.zuliprc_content}
            </Text>{" "}
            <button
              className="ml-1 hover:bg-hover rounded p-1"
              onClick={async () => {
                await adminDeleteCredential(zulipCredential.id);
                refreshCredentials();
              }}
            >
              <TrashIcon />
            </button>
          </div>
        </>
      ) : (
        <>
          <Text className="mb-4">
            To use the Zulip connector, you must first provide content of the
            zuliprc config file. For more details on setting up the Danswer
            Zulip connector, see the{" "}
            <a
              className="text-link"
              href="https://docs.danswer.dev/connectors/zulip"
              target="_blank"
            >
              docs
            </a>
            .
          </Text>
          <Card className="mt-4">
            <CredentialForm<ZulipCredentialJson>
              formBody={
                <>
                  <TextFormField
                    name="zuliprc_content"
                    label="Content of the zuliprc file:"
                    type="text"
                  />
                </>
              }
              validationSchema={Yup.object().shape({
                zuliprc_content: Yup.string().required(
                  "Please enter content of the zuliprc file"
                ),
              })}
              initialValues={{
                zuliprc_content: "",
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
        Step 2: Which workspaces do you want to make searchable?
      </Title>

      {zulipCredential ? (
        <>
          {zulipConnectorIndexingStatuses.length > 0 && (
            <>
              <Text className="mb-2">
                We pull the latest messages from each workspace listed below
                every <b>10</b> minutes.
              </Text>
              <div className="mb-2">
                <ConnectorsTable
                  connectorIndexingStatuses={zulipConnectorIndexingStatuses}
                  liveCredential={zulipCredential}
                  getCredential={(credential) =>
                    credential.credential_json.zuliprc_content
                  }
                  specialColumns={[
                    {
                      header: "Realm name",
                      key: "realm_name",
                      getValue: (ccPairStatus) =>
                        ccPairStatus.connector.connector_specific_config
                          .realm_name,
                    },
                    {
                      header: "Realm url",
                      key: "realm_url",
                      getValue: (ccPairStatus) =>
                        ccPairStatus.connector.connector_specific_config
                          .realm_url,
                    },
                  ]}
                  onUpdate={() =>
                    mutate("/api/manage/admin/connector/indexing-status")
                  }
                  onCredentialLink={async (connectorId) => {
                    if (zulipCredential) {
                      await linkCredential(connectorId, zulipCredential.id);
                      mutate("/api/manage/admin/connector/indexing-status");
                    }
                  }}
                />
              </div>
              <Divider />
            </>
          )}

          <Card className="mt-4">
            <h2 className="font-bold mb-3">Connect to a New Realm</h2>
            <ConnectorForm<ZulipConfig>
              nameBuilder={(values) => `ZulipConnector-${values.realm_name}`}
              ccPairNameBuilder={(values) => values.realm_name}
              source="zulip"
              inputType="poll"
              credentialId={zulipCredential.id}
              formBody={
                <>
                  <TextFormField name="realm_name" label="Realm name:" />
                  <TextFormField name="realm_url" label="Realm url:" />
                </>
              }
              validationSchema={Yup.object().shape({
                realm_name: Yup.string().required(
                  "Please enter the realm name"
                ),
                realm_url: Yup.string().required("Please enter the realm url"),
              })}
              initialValues={{
                realm_name: "",
                realm_url: "",
              }}
              refreshFreq={10 * 60} // 10 minutes
            />
          </Card>
        </>
      ) : (
        <Text>
          Please provide your Zulip credentials in Step 1 first! Once done with
          that, you can then specify which Zulip realms you want to make
          searchable.
        </Text>
      )}
    </>
  );
};

export default function Page() {
  return (
    <div className="mx-auto container">
      <AdminPageTitle icon={<ZulipIcon size={32} />} title="Zulip" />

      <MainSection />
    </div>
  );
}
