"use client";

import * as Yup from "yup";
import { TrashIcon, SalesforceIcon } from "@/components/icons/icons"; // Make sure you have a Document360 icon
import { errorHandlingFetcher as fetcher } from "@/lib/fetcher";
import useSWR, { useSWRConfig } from "swr";
import { LoadingAnimation } from "@/components/Loading";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import {
  SfKbArticlesConfig,
  SfKbArticlesCredentialJson,
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
    error: isConnectorIndexingStatusesError,
  } = useSWR<ConnectorIndexingStatus<any, any>[]>(
    "/api/manage/admin/connector/indexing-status",
    fetcher
  );

  const {
    data: credentialsData,
    isLoading: isCredentialsLoading,
    error: isCredentialsError,
    refreshCredentials,
  } = usePublicCredentials();

  if (
    (!connectorIndexingStatuses && isConnectorIndexingStatusesLoading) ||
    (!credentialsData && isCredentialsLoading)
  ) {
    return <LoadingAnimation text="Loading" />;
  }

  if (isConnectorIndexingStatusesError || !connectorIndexingStatuses) {
    return <div>Failed to load connectors</div>;
  }

  if (isCredentialsError || !credentialsData) {
    return <div>Failed to load credentials</div>;
  }

  const SalesforceConnectorIndexingStatuses: ConnectorIndexingStatus<
    SfKbArticlesConfig,
    SfKbArticlesCredentialJson
  >[] = connectorIndexingStatuses.filter(
    (connectorIndexingStatus) =>
      connectorIndexingStatus.connector.source === "salesforce"
  );

  const SfKbArticlesCredential:
    | Credential<SfKbArticlesCredentialJson>
    | undefined = credentialsData.find(
    (credential) => credential.credential_json?.sf_username
  );

  return (
    <>
      <Text>
        The Salesforce Knowledge Base Articles connector allows you to index and
        search through your Salesforce Knowledge Base. Once setup, all indicated
        Salesforce data will be queryable within Darwin.
      </Text>

      <Title className="mb-2 mt-6 ml-auto mr-auto">
        Step 1: Provide Salesforce credentials
      </Title>
      {SfKbArticlesCredential ? (
        <>
          <div className="flex mb-1 text-sm">
            <Text className="my-auto">Existing SalesForce Username: </Text>
            <Text className="ml-1 italic my-auto">
              {SfKbArticlesCredential.credential_json.sf_username}
            </Text>
            <button
              className="ml-1 hover:bg-hover rounded p-1"
              onClick={async () => {
                await adminDeleteCredential(SfKbArticlesCredential.id);
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
            As a first step, please provide the Salesforce account&apos;s
            client_id, client_secret, username and password.
          </Text>
          <Card className="mt-2">
            <CredentialForm<SfKbArticlesCredentialJson>
              formBody={
                <>
                  <TextFormField
                    name="sf_client_id"
                    label="Salesforce Client Id:"
                  />
                  <TextFormField
                    name="sf_client_secret"
                    label="Salesforce Client Secret:"
                    type="password"
                  />
                  <TextFormField
                    name="sf_username"
                    label="Salesforce Username:"
                  />
                  <TextFormField
                    name="sf_password"
                    label="Salesforce Password:"
                    type="password"
                  />
                </>
              }
              validationSchema={Yup.object().shape({
                sf_client_id: Yup.string().required(
                  "Please enter your Salesforce Client Id"
                ),
                sf_client_secret: Yup.string().required(
                  "Please enter your Salesforce Client Secret"
                ),
                sf_username: Yup.string().required(
                  "Please enter your Salesforce username"
                ),
                sf_password: Yup.string().required(
                  "Please enter your Salesforce password"
                ),
              })}
              initialValues={{
                sf_client_id: "",
                sf_client_secret: "",
                sf_username: "",
                sf_password: "",
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
        Step 2: Manage Salesforce KB Articles Connector
      </Title>

      {SalesforceConnectorIndexingStatuses.length > 0 && (
        <>
          <Text className="mb-2">
            The latest state of your Salesforce objects are fetched every 10
            minutes.
          </Text>
          <div className="mb-2">
            <ConnectorsTable<SfKbArticlesConfig, SfKbArticlesCredentialJson>
              connectorIndexingStatuses={SalesforceConnectorIndexingStatuses}
              liveCredential={SfKbArticlesCredential}
              getCredential={(credential) =>
                credential.credential_json.sf_client_secret
              }
              onUpdate={() =>
                mutate("/api/manage/admin/connector/indexing-status")
              }
              onCredentialLink={async (connectorId) => {
                if (SfKbArticlesCredential) {
                  await linkCredential(connectorId, SfKbArticlesCredential.id);
                  mutate("/api/manage/admin/connector/indexing-status");
                }
              }}
              specialColumns={[
                {
                  header: "Connectors",
                  key: "connectors",
                  getValue: (ccPairStatus) => {
                    const connectorConfig =
                      ccPairStatus.connector.connector_specific_config;
                    return `${connectorConfig.requested_objects}`;
                  },
                },
              ]}
              includeName
            />
          </div>
        </>
      )}

      {SfKbArticlesCredential ? (
        <Card className="mt-4">
          <ConnectorForm<SfKbArticlesConfig>
            nameBuilder={(values) =>
              values.requested_objects && values.requested_objects.length > 0
                ? `SfKbArticles-${values.requested_objects.join("-")}`
                : "SfKbArticles"
            }
            ccPairNameBuilder={(values) =>
              values.requested_objects && values.requested_objects.length > 0
                ? `SfKbArticles-${values.requested_objects.join("-")}`
                : "SfKbArticles"
            }
            source="sfkbarticles"
            inputType="poll"
            // formBody={<></>}
            formBodyBuilder={TextArrayFieldBuilder({
              name: "requested_objects",
              label: "Specify the Product Components",
              subtext: (
                <>
                  <br />
                  Specify the product components for which you want to fetch the
                  Salesforce Knowledge Base articles.
                  <br />
                  <br />
                  Example:{" "}
                  <strong>
                    Orchestrator, Activities, Studio, Robot, Automation Hub
                  </strong>
                  .
                  <br />
                  <br />
                  By default, it will fetch articles for all the product
                  components.
                  <br />
                  <br />
                  Hint: Use the exact product component name for accurate
                  results.
                </>
              ),
            })}
            validationSchema={Yup.object().shape({
              requested_objects: Yup.array()
                .of(
                  Yup.string().required(
                    "Salesforce Product Component names must be strings"
                  )
                )
                .required(),
            })}
            initialValues={{
              requested_objects: [],
            }}
            credentialId={SfKbArticlesCredential.id}
            refreshFreq={10 * 60} // 10 minutes
          />
        </Card>
      ) : (
        <Text>
          Please provide all Salesforce info in Step 1 first! Once you&apos;re
          done with that, you can then specify the product components for which
          you want to fetch the Salesforce Knowledge Base articles.
        </Text>
      )}
    </>
  );
};

export default function Page() {
  return (
    <div className="mx-auto container">
      <div className="mb-4">
        <HealthCheckBanner />
      </div>

      <AdminPageTitle
        icon={<SalesforceIcon size={32} />}
        title="Salesforce KB Articles"
      />

      <MainSection />
    </div>
  );
}
