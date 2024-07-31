"use client";

import * as Yup from "yup";
import { DiscourseIcon, TrashIcon } from "@/components/icons/icons";
import {
  TextFormField,
  TextArrayFieldBuilder,
} from "@/components/admin/connectors/Field";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import { CredentialForm } from "@/components/admin/connectors/CredentialForm";
import {
  Credential,
  ConnectorIndexingStatus,
  DiscourseConfig,
  DiscourseCredentialJson,
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
import { Card, Divider, Text, Title } from "@tremor/react";
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

  const discourseConnectorIndexingStatuses: ConnectorIndexingStatus<
    DiscourseConfig,
    DiscourseCredentialJson
  >[] = connectorIndexingStatuses.filter(
    (connectorIndexingStatus) =>
      connectorIndexingStatus.connector.source === "discourse"
  );
  const discourseCredential: Credential<DiscourseCredentialJson> | undefined =
    credentialsData.find(
      (credential) => credential.credential_json?.discourse_api_username
    );

  return (
    <>
      {popup}
      <Text>
        This connector allows you to sync all your Discourse Topics into
        Danswer. More details on how to setup the Discourse connector can be
        found in{" "}
        <a
          className="text-link"
          href="https://docs.danswer.dev/connectors/discourse"
          target="_blank"
        >
          this guide.
        </a>
      </Text>

      <Title className="mb-2 mt-6 ml-auto mr-auto">
        Step 1: Provide your API Access info
      </Title>

      {discourseCredential ? (
        <>
          <div className="flex mb-1 text-sm">
            <p className="my-auto">Existing API Key: </p>
            <p className="ml-1 italic my-auto max-w-md truncate">
              {discourseCredential.credential_json?.discourse_api_key}
            </p>
            <button
              className="ml-1 hover:bg-hover rounded p-1"
              onClick={async () => {
                if (discourseConnectorIndexingStatuses.length > 0) {
                  setPopup({
                    type: "error",
                    message:
                      "Must delete all connectors before deleting credentials",
                  });
                  return;
                }
                await adminDeleteCredential(discourseCredential.id);
                refreshCredentials();
              }}
            >
              <TrashIcon />
            </button>
          </div>
        </>
      ) : (
        <>
          <Card className="mt-4">
            <CredentialForm<DiscourseCredentialJson>
              formBody={
                <>
                  <TextFormField
                    name="discourse_api_username"
                    label="API Key Username:"
                  />
                  <TextFormField
                    name="discourse_api_key"
                    label="API Key:"
                    type="password"
                  />
                </>
              }
              validationSchema={Yup.object().shape({
                discourse_api_username: Yup.string().required(
                  "Please enter the Username associated with the API key"
                ),
                discourse_api_key: Yup.string().required(
                  "Please enter the API key"
                ),
              })}
              initialValues={{
                discourse_api_username: "",
                discourse_api_key: "",
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
        Step 2: Which Categories do you want to make searchable?
      </Title>

      {discourseConnectorIndexingStatuses.length > 0 && (
        <>
          <Text className="mb-2">
            We pull Topics with new Posts every <b>10</b> minutes.
          </Text>
          <div className="mb-2">
            <ConnectorsTable<DiscourseConfig, DiscourseCredentialJson>
              connectorIndexingStatuses={discourseConnectorIndexingStatuses}
              liveCredential={discourseCredential}
              getCredential={(credential) =>
                credential.credential_json.discourse_api_username
              }
              specialColumns={[
                {
                  header: "Categories",
                  key: "categories",
                  getValue: (ccPairStatus) =>
                    ccPairStatus.connector.connector_specific_config
                      .categories &&
                    ccPairStatus.connector.connector_specific_config.categories
                      .length > 0
                      ? ccPairStatus.connector.connector_specific_config.categories.join(
                          ", "
                        )
                      : "",
                },
              ]}
              includeName={true}
              onUpdate={() =>
                mutate("/api/manage/admin/connector/indexing-status")
              }
              onCredentialLink={async (connectorId) => {
                if (discourseCredential) {
                  await linkCredential(connectorId, discourseCredential.id);
                  mutate("/api/manage/admin/connector/indexing-status");
                }
              }}
            />
          </div>
          <Divider />
        </>
      )}

      {discourseCredential ? (
        <>
          <Card className="mt-4">
            <h2 className="font-bold mb-3">Create a new Discourse Connector</h2>
            <ConnectorForm<DiscourseConfig>
              nameBuilder={(values) =>
                values.categories
                  ? `${values.base_url}-${values.categories.join("_")}`
                  : `${values.base_url}-All`
              }
              source="discourse"
              inputType="poll"
              formBody={
                <>
                  <TextFormField
                    name="base_url"
                    label="Base URL:"
                    subtext="This might be something like https://danswer.discourse.group/ or https://community.yourcompany.com/"
                  />
                </>
              }
              formBodyBuilder={TextArrayFieldBuilder({
                name: "categories",
                label: "Categories:",
                subtext:
                  "Specify 0 or more Categories to index. If no Categories are specified, Topics from " +
                  "all categories will be indexed.",
              })}
              validationSchema={Yup.object().shape({
                base_url: Yup.string().required(
                  "Please the base URL of your Discourse site."
                ),
                categories: Yup.array().of(
                  Yup.string().required("Category names must be strings")
                ),
              })}
              initialValues={{
                categories: [],
                base_url: "",
              }}
              refreshFreq={10 * 60} // 10 minutes
              credentialId={discourseCredential.id}
            />
          </Card>
        </>
      ) : (
        <Text>
          Please provide your API Key Info in Step 1 first! Once done with that,
          you can then start indexing all your Discourse Topics.
        </Text>
      )}
    </>
  );
};

export default function Page() {
  return (
    <div className="mx-auto container">
      <AdminPageTitle icon={<DiscourseIcon size={32} />} title="Discourse" />

      <Main />
    </div>
  );
}
