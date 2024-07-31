"use client";

import * as Yup from "yup";
import { TrashIcon, ClickupIcon } from "@/components/icons/icons";
import { errorHandlingFetcher } from "@/lib/fetcher";
import useSWR, { useSWRConfig } from "swr";
import { LoadingAnimation } from "@/components/Loading";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import {
  ClickupConfig,
  ClickupCredentialJson,
  ConnectorIndexingStatus,
  Credential,
} from "@/lib/types";
import { adminDeleteCredential, linkCredential } from "@/lib/credential";
import { CredentialForm } from "@/components/admin/connectors/CredentialForm";
import {
  BooleanFormField,
  SelectorFormField,
  TextFormField,
  TextArrayFieldBuilder,
} from "@/components/admin/connectors/Field";
import { ConnectorsTable } from "@/components/admin/connectors/table/ConnectorsTable";
import { ConnectorForm } from "@/components/admin/connectors/ConnectorForm";
import { usePopup } from "@/components/admin/connectors/Popup";
import { usePublicCredentials } from "@/lib/hooks";
import { Title, Text, Card, Divider } from "@tremor/react";
import { AdminPageTitle } from "@/components/admin/Title";

const MainSection = () => {
  const { mutate } = useSWRConfig();
  const { popup, setPopup } = usePopup();
  const {
    data: connectorIndexingStatuses,
    isLoading: isConnectorIndexingStatusesLoading,
    error: isConnectorIndexingStatusesError,
  } = useSWR<ConnectorIndexingStatus<any, any>[]>(
    "/api/manage/admin/connector/indexing-status",
    errorHandlingFetcher
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

  const clickupConnectorIndexingStatuses: ConnectorIndexingStatus<
    ClickupConfig,
    ClickupCredentialJson
  >[] = connectorIndexingStatuses.filter(
    (connectorIndexingStatus) =>
      connectorIndexingStatus.connector.source === "clickup"
  );

  const clickupCredential: Credential<ClickupCredentialJson> | undefined =
    credentialsData.find(
      (credential) => credential.credential_json?.clickup_api_token
    );

  return (
    <>
      {popup}
      <Title className="mb-2 mt-6 ml-auto mr-auto">
        Step 1: Provide Credentials
      </Title>

      {clickupCredential ? (
        <>
          <div className="flex mb-1 text-sm">
            <Text className="my-auto">Existing Clickup API Token: </Text>
            <Text className="ml-1 italic my-auto">
              {clickupCredential.credential_json.clickup_api_token}
            </Text>
            <button
              className="ml-1 hover:bg-hover rounded p-1"
              onClick={async () => {
                if (clickupConnectorIndexingStatuses.length > 0) {
                  setPopup({
                    type: "error",
                    message:
                      "Must delete all connectors before deleting credentials",
                  });
                  return;
                }
                await adminDeleteCredential(clickupCredential.id);
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
            To use the Clickup connector, you must first provide the API token
            and Team ID corresponding to your Clickup setup. See setup guide{" "}
            <a
              className="text-link"
              href="https://docs.danswer.dev/connectors/clickup"
              target="_blank"
            >
              here
            </a>{" "}
            for more detail.
          </Text>
          <Card className="mt-2">
            <CredentialForm<ClickupCredentialJson>
              formBody={
                <>
                  <TextFormField
                    name="clickup_api_token"
                    label="Clickup API Token:"
                    type="password"
                  />
                  <TextFormField name="clickup_team_id" label="Team ID:" />
                </>
              }
              validationSchema={Yup.object().shape({
                clickup_api_token: Yup.string().required(
                  "Please enter your Clickup API token"
                ),
                clickup_team_id: Yup.string().required(
                  "Please enter your Team ID"
                ),
              })}
              initialValues={{
                clickup_api_token: "",
                clickup_team_id: "",
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
        Step 2: Do you want to search particular space(s), folder(s), list(s),
        or entire workspace?
      </Title>

      {clickupConnectorIndexingStatuses.length > 0 && (
        <>
          <Text className="mb-2">
            We index the latest articles from either the entire workspace, or
            specified space(s), folder(s), list(s) listed below regularly.
          </Text>
          <div className="mb-2">
            <ConnectorsTable<ClickupConfig, ClickupCredentialJson>
              connectorIndexingStatuses={clickupConnectorIndexingStatuses}
              liveCredential={clickupCredential}
              getCredential={(credential) =>
                credential.credential_json.clickup_api_token
              }
              specialColumns={[
                {
                  header: "Connector Type",
                  key: "connector_type",
                  getValue: (ccPairStatus) =>
                    ccPairStatus.connector.connector_specific_config
                      .connector_type,
                },
                {
                  header: "ID(s)",
                  key: "connector_ids",
                  getValue: (ccPairStatus) =>
                    ccPairStatus.connector.connector_specific_config
                      .connector_ids &&
                    ccPairStatus.connector.connector_specific_config
                      .connector_ids.length > 0
                      ? ccPairStatus.connector.connector_specific_config.connector_ids.join(
                          ", "
                        )
                      : "",
                },
                {
                  header: "Retrieve Task Comments?",
                  key: "retrieve_task_comments",
                  getValue: (ccPairStatus) =>
                    ccPairStatus.connector.connector_specific_config
                      .retrieve_task_comments
                      ? "Yes"
                      : "No",
                },
              ]}
              onUpdate={() =>
                mutate("/api/manage/admin/connector/indexing-status")
              }
              onCredentialLink={async (connectorId) => {
                if (clickupCredential) {
                  await linkCredential(connectorId, clickupCredential.id);
                  mutate("/api/manage/admin/connector/indexing-status");
                }
              }}
            />
          </div>
          <Divider />
        </>
      )}

      {clickupCredential ? (
        <Card className="mt-4">
          <h2 className="font-bold mb-3">Connect to a New Workspace</h2>
          <ConnectorForm<ClickupConfig>
            nameBuilder={(values) =>
              values.connector_ids
                ? `ClickupConnector-${
                    values.connector_type
                  }-${values.connector_ids.join("_")}`
                : `ClickupConnector-${values.connector_type}`
            }
            source="clickup"
            inputType="poll"
            formBody={
              <>
                <SelectorFormField
                  name="connector_type"
                  label="Connector Type:"
                  options={[
                    {
                      name: "Entire Workspace",
                      value: "workspace",
                      description:
                        "Recursively index all tasks from the entire workspace",
                    },
                    {
                      name: "Space(s)",
                      value: "space",
                      description:
                        "Index tasks only from the specified space id(s).",
                    },
                    {
                      name: "Folder(s)",
                      value: "folder",
                      description:
                        "Index tasks only from the specified folder id(s).",
                    },
                    {
                      name: "List(s)",
                      value: "list",
                      description:
                        "Index tasks only from the specified list id(s).",
                    },
                  ]}
                />
              </>
            }
            formBodyBuilder={(values) => {
              return (
                <>
                  <Divider />
                  {TextArrayFieldBuilder({
                    name: "connector_ids",
                    label: "ID(s):",
                    subtext: "Specify 0 or more id(s) to index from.",
                  })(values)}
                  <BooleanFormField
                    name="retrieve_task_comments"
                    label="Retrieve Task Comments?"
                    subtext={
                      "If checked, then all the comments for each task will also be retrieved and indexed."
                    }
                  />
                </>
              );
            }}
            validationSchema={Yup.object().shape({
              connector_type: Yup.string()
                .oneOf(["workspace", "space", "folder", "list"])
                .required("Please select the connector_type to index"),
              connector_ids: Yup.array()
                .of(Yup.string().required("ID(s) must be strings"))
                .test(
                  "idsRequired",
                  "At least 1 ID is required if space, folder or list is selected",
                  function (value) {
                    if (this.parent.connector_type === "workspace") return true;
                    else if (value !== undefined && value.length > 0)
                      return true;
                    setPopup({
                      type: "error",
                      message: `Add at least one ${this.parent.connector_type} ID`,
                    });
                    return false;
                  }
                ),
              retrieve_task_comments: Yup.boolean().required(),
            })}
            initialValues={{
              connector_type: "workspace",
              connector_ids: [],
              retrieve_task_comments: true,
            }}
            refreshFreq={10 * 60} // 10 minutes
            credentialId={clickupCredential.id}
          />
        </Card>
      ) : (
        <Text>
          Please provide your Clickup API token and Team ID in Step 1 first!
          Once done with that, you can then specify whether you want to make the
          entire workspace, or specified space(s), folder(s), list(s)
          searchable.
        </Text>
      )}
    </>
  );
};

export default function Page() {
  return (
    <div className="mx-auto container">
      <AdminPageTitle icon={<ClickupIcon size={32} />} title="Clickup" />

      <MainSection />
    </div>
  );
}
