"use client";

import * as Yup from "yup";
import { SlackIcon, TrashIcon } from "@/components/icons/icons";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { ErrorCallout } from "@/components/ErrorCallout";
import useSWR, { useSWRConfig } from "swr";
import { LoadingAnimation } from "@/components/Loading";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import {
  SlackConfig,
  SlackCredentialJson,
  ConnectorIndexingStatus,
  Credential,
} from "@/lib/types";
import { adminDeleteCredential, linkCredential } from "@/lib/credential";
import { CredentialForm } from "@/components/admin/connectors/CredentialForm";
import {
  TextFormField,
  TextArrayFieldBuilder,
  BooleanFormField,
  TextArrayField,
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

  const slackConnectorIndexingStatuses: ConnectorIndexingStatus<
    SlackConfig,
    SlackCredentialJson
  >[] = connectorIndexingStatuses.filter(
    (connectorIndexingStatus) =>
      connectorIndexingStatus.connector.source === "slack"
  );
  const slackCredential: Credential<SlackCredentialJson> | undefined =
    credentialsData.find(
      (credential) => credential.credential_json?.slack_bot_token
    );

  return (
    <>
      <Title className="mb-2 mt-6 ml-auto mr-auto">
        Step 1: Provide Credentials
      </Title>
      {slackCredential ? (
        <>
          <div className="flex mb-1 text-sm">
            <Text className="my-auto">Existing Slack Bot Token: </Text>
            <Text className="ml-1 italic my-auto">
              {slackCredential.credential_json.slack_bot_token}
            </Text>
            <Button
              size="xs"
              color="red"
              className="ml-3 text-inverted"
              onClick={async () => {
                await adminDeleteCredential(slackCredential.id);
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
            To use the Slack connector, you must first provide a Slack bot token
            corresponding to the Slack App set up in your workspace. For more
            details on setting up the Danswer Slack App, see the{" "}
            <a
              className="text-blue-500"
              href="https://docs.danswer.dev/connectors/slack#setting-up"
            >
              docs
            </a>
            .
          </p>
          <Card>
            <CredentialForm<SlackCredentialJson>
              formBody={
                <>
                  <TextFormField
                    name="slack_bot_token"
                    label="Slack Bot Token:"
                    type="password"
                  />
                </>
              }
              validationSchema={Yup.object().shape({
                slack_bot_token: Yup.string().required(
                  "Please enter your Slack bot token"
                ),
              })}
              initialValues={{
                slack_bot_token: "",
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
        Step 2: Which channels do you want to make searchable?
      </Title>

      {slackConnectorIndexingStatuses.length > 0 && (
        <>
          <Text className="mb-2">
            We pull the latest messages from each workspace listed below every{" "}
            <b>10</b> minutes.
          </Text>
          <div className="mb-2">
            <ConnectorsTable<SlackConfig, SlackCredentialJson>
              connectorIndexingStatuses={slackConnectorIndexingStatuses}
              liveCredential={slackCredential}
              getCredential={(credential) =>
                credential.credential_json.slack_bot_token
              }
              specialColumns={[
                {
                  header: "Workspace",
                  key: "workspace",
                  getValue: (ccPairStatus) =>
                    ccPairStatus.connector.connector_specific_config.workspace,
                },
                {
                  header: "Channels",
                  key: "channels",
                  getValue: (ccPairStatus) => {
                    const connectorConfig =
                      ccPairStatus.connector.connector_specific_config;
                    return connectorConfig.channels &&
                      connectorConfig.channels.length > 0
                      ? connectorConfig.channels.join(", ")
                      : "";
                  },
                },
              ]}
              onUpdate={() =>
                mutate("/api/manage/admin/connector/indexing-status")
              }
              onCredentialLink={async (connectorId) => {
                if (slackCredential) {
                  await linkCredential(connectorId, slackCredential.id);
                  mutate("/api/manage/admin/connector/indexing-status");
                }
              }}
            />
          </div>
          <Divider />
        </>
      )}

      {slackCredential ? (
        <Card>
          <h2 className="font-bold mb-3">Connect to a New Workspace</h2>
          <ConnectorForm<SlackConfig>
            nameBuilder={(values) =>
              values.channels
                ? `SlackConnector-${values.workspace}-${values.channels.join(
                    "_"
                  )}`
                : `SlackConnector-${values.workspace}`
            }
            source="slack"
            inputType="poll"
            formBody={
              <>
                <TextFormField name="workspace" label="Workspace" />
              </>
            }
            formBodyBuilder={(values) => {
              return (
                <>
                  <Divider />
                  {TextArrayFieldBuilder({
                    name: "channels",
                    label: "Channels:",
                    subtext: `
                      Specify 0 or more channels to index. For example, specifying the channel
                      "support" will cause us to only index all content within the "#support" channel.
                      If no channels are specified, all channels in your workspace will be indexed.`,
                  })(values)}
                  <BooleanFormField
                    name="channel_regex_enabled"
                    label="Regex Enabled?"
                    subtext={
                      <div>
                        If enabled, we will treat the &quot;channels&quot;
                        specified above as regular expressions. A channel&apos;s
                        messages will be pulled in by the connector if the name
                        of the channel fully matches any of the specified
                        regular expressions.
                        <br />
                        For example, specifying <i>.*-support.*</i> as a
                        &quot;channel&quot; will cause the connector to include
                        any channels with &quot;-support&quot; in the name.
                      </div>
                    }
                  />
                </>
              );
            }}
            validationSchema={Yup.object().shape({
              workspace: Yup.string().required(
                "Please enter the workspace to index"
              ),
              channels: Yup.array()
                .of(Yup.string().required("Channel names must be strings"))
                .required(),
              channel_regex_enabled: Yup.boolean().required(),
            })}
            initialValues={{
              workspace: "",
              channels: [],
              channel_regex_enabled: false,
            }}
            refreshFreq={10 * 60} // 10 minutes
            credentialId={slackCredential.id}
          />
        </Card>
      ) : (
        <Text>
          Please provide your slack bot token in Step 1 first! Once done with
          that, you can then specify which Slack channels you want to make
          searchable.
        </Text>
      )}
    </>
  );
};

export default function Page() {
  return (
    <div className="mx-auto container">
      <AdminPageTitle icon={<SlackIcon size={32} />} title="Slack" />

      <MainSection />
    </div>
  );
}
