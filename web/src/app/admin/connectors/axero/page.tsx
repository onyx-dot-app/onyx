"use client";

import * as Yup from "yup";
import { AxeroIcon, TrashIcon } from "@/components/icons/icons";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { ErrorCallout } from "@/components/ErrorCallout";
import useSWR, { useSWRConfig } from "swr";
import { LoadingAnimation } from "@/components/Loading";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import {
  AxeroConfig,
  AxeroCredentialJson,
  ConnectorIndexingStatus,
  Credential,
} from "@/lib/types";
import { adminDeleteCredential, linkCredential } from "@/lib/credential";
import { CredentialForm } from "@/components/admin/connectors/CredentialForm";
import {
  TextFormField,
  TextArrayFieldBuilder,
} from "@/components/admin/connectors/Field";
import { ConnectorsTable } from "@/components/admin/connectors/table/ConnectorsTable";
import { ConnectorForm } from "@/components/admin/connectors/ConnectorForm";
import { usePublicCredentials } from "@/lib/hooks";
import { Button, Card, Divider, Text, Title } from "@tremor/react";
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

  const axeroConnectorIndexingStatuses: ConnectorIndexingStatus<
    AxeroConfig,
    AxeroCredentialJson
  >[] = connectorIndexingStatuses.filter(
    (connectorIndexingStatus) =>
      connectorIndexingStatus.connector.source === "axero"
  );
  const axeroCredential: Credential<AxeroCredentialJson> | undefined =
    credentialsData.find(
      (credential) => credential.credential_json?.axero_api_token
    );

  return (
    <>
      <Title className="mb-2 mt-6 ml-auto mr-auto">
        Step 1: Provide Axero API Key
      </Title>
      {axeroCredential ? (
        <>
          <div className="flex mb-1 text-sm">
            <Text className="my-auto">Existing Axero API Key: </Text>
            <Text className="ml-1 italic my-auto">
              {axeroCredential.credential_json.axero_api_token}
            </Text>
            <Button
              size="xs"
              color="red"
              className="ml-3 text-inverted"
              onClick={async () => {
                await adminDeleteCredential(axeroCredential.id);
                refreshCredentials();
              }}
            >
              <TrashIcon />
            </Button>
          </div>
        </>
      ) : (
        <>
          <p className="text-sm mb-4">
            To use the Axero connector, first follow the guide{" "}
            <a
              className="text-blue-500"
              href="https://docs.danswer.dev/connectors/axero"
              target="_blank"
            >
              here
            </a>{" "}
            to generate an API Key.
          </p>
          <Card>
            <CredentialForm<AxeroCredentialJson>
              formBody={
                <>
                  <TextFormField name="base_url" label="Axero Base URL:" />
                  <TextFormField
                    name="axero_api_token"
                    label="Axero API Key:"
                    type="password"
                  />
                </>
              }
              validationSchema={Yup.object().shape({
                base_url: Yup.string().required(
                  "Please enter the base URL of your Axero instance"
                ),
                axero_api_token: Yup.string().required(
                  "Please enter your Axero API Token"
                ),
              })}
              initialValues={{
                base_url: "",
                axero_api_token: "",
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
        Step 2: Which spaces do you want to connect?
      </Title>

      {axeroConnectorIndexingStatuses.length > 0 && (
        <>
          <Text className="mb-2">
            We pull the latest <i>Articles</i>, <i>Blogs</i>, <i>Wikis</i> and{" "}
            <i>Forums</i> once per day.
          </Text>
          <div className="mb-2">
            <ConnectorsTable<AxeroConfig, AxeroCredentialJson>
              connectorIndexingStatuses={axeroConnectorIndexingStatuses}
              liveCredential={axeroCredential}
              getCredential={(credential) =>
                credential.credential_json.axero_api_token
              }
              specialColumns={[
                {
                  header: "Space",
                  key: "spaces",
                  getValue: (ccPairStatus) => {
                    const connectorConfig =
                      ccPairStatus.connector.connector_specific_config;
                    return connectorConfig.spaces &&
                      connectorConfig.spaces.length > 0
                      ? connectorConfig.spaces.join(", ")
                      : "";
                  },
                },
              ]}
              onUpdate={() =>
                mutate("/api/manage/admin/connector/indexing-status")
              }
              onCredentialLink={async (connectorId) => {
                if (axeroCredential) {
                  await linkCredential(connectorId, axeroCredential.id);
                  mutate("/api/manage/admin/connector/indexing-status");
                }
              }}
            />
          </div>
          <Divider />
        </>
      )}

      {axeroCredential ? (
        <Card>
          <h2 className="font-bold mb-3">Configure an Axero Connector</h2>
          <ConnectorForm<AxeroConfig>
            nameBuilder={(values) =>
              values.spaces
                ? `AxeroConnector-${values.spaces.join("_")}`
                : `AxeroConnector`
            }
            source="axero"
            inputType="poll"
            formBodyBuilder={(values) => {
              return (
                <>
                  <Divider />
                  {TextArrayFieldBuilder({
                    name: "spaces",
                    label: "Space IDs:",
                    subtext: `
                      Specify zero or more Spaces to index (by the Space IDs). If no Space IDs
                      are specified, all Spaces will be indexed.`,
                  })(values)}
                </>
              );
            }}
            validationSchema={Yup.object().shape({
              spaces: Yup.array()
                .of(Yup.string().required("Space Ids cannot be empty"))
                .required(),
            })}
            initialValues={{
              spaces: [],
            }}
            refreshFreq={60 * 60 * 24} // 1 day
            credentialId={axeroCredential.id}
          />
        </Card>
      ) : (
        <Text>
          Please provide your Axero API Token in Step 1 first! Once done with
          that, you can then specify which spaces you want to connect.
        </Text>
      )}
    </>
  );
};

export default function Page() {
  return (
    <div className="mx-auto container">
      <AdminPageTitle icon={<AxeroIcon size={32} />} title="Axero" />

      <MainSection />
    </div>
  );
}
