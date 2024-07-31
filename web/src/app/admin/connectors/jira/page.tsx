"use client";

import * as Yup from "yup";
import { JiraIcon, TrashIcon } from "@/components/icons/icons";
import {
  TextFormField,
  TextArrayFieldBuilder,
} from "@/components/admin/connectors/Field";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import { CredentialForm } from "@/components/admin/connectors/CredentialForm";
import {
  JiraConfig,
  JiraCredentialJson,
  JiraServerCredentialJson,
  ConnectorIndexingStatus,
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
import { Card, Divider, Text, Title } from "@tremor/react";

// Copied from the `extract_jira_project` function
const extractJiraProject = (url: string): string | null => {
  const parsedUrl = new URL(url);
  const splitPath = parsedUrl.pathname.split("/");
  const projectPos = splitPath.indexOf("projects");
  if (projectPos !== -1 && splitPath.length > projectPos + 1) {
    const jiraProject = splitPath[projectPos + 1];
    return jiraProject;
  }
  return null;
};

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

  const jiraConnectorIndexingStatuses: ConnectorIndexingStatus<
    JiraConfig,
    JiraCredentialJson | JiraServerCredentialJson
  >[] = connectorIndexingStatuses.filter(
    (connectorIndexingStatus) =>
      connectorIndexingStatus.connector.source === "jira"
  );
  const jiraCredential = credentialsData.filter(
    (credential) => credential.credential_json?.jira_api_token
  )[0];

  return (
    <>
      {popup}
      <Title className="mb-2 mt-6 ml-auto mr-auto">
        Step 1: Provide your Credentials
      </Title>

      {jiraCredential ? (
        <>
          <div className="flex mb-1 text-sm">
            <p className="my-auto">Existing Access Token: </p>
            <p className="ml-1 italic my-auto max-w-md truncate">
              {jiraCredential.credential_json?.jira_api_token}
            </p>
            <button
              className="ml-1 hover:bg-gray-700 rounded-full p-1"
              onClick={async () => {
                if (jiraConnectorIndexingStatuses.length > 0) {
                  setPopup({
                    type: "error",
                    message:
                      "Must delete all connectors before deleting credentials",
                  });
                  return;
                }
                const response = await adminDeleteCredential(jiraCredential.id);
                if (response.ok) {
                  setPopup({
                    type: "success",
                    message: "Successfully deleted credential!",
                  });
                } else {
                  const errorMsg = await response.text();
                  setPopup({
                    type: "error",
                    message: `Failed to delete credential - ${errorMsg}`,
                  });
                }
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
            To use the Jira connector, first follow the guide{" "}
            <a
              className="text-link"
              href="https://docs.danswer.dev/connectors/jira#setting-up"
              target="_blank"
            >
              here
            </a>{" "}
            to generate an Access Token (for cloud) or Personal Access Token
            (for server). Submit only one form.
          </Text>
          <Title className="mb-2 mt-6 ml-auto mr-auto">Cloud</Title>
          <Card className="mt-4">
            <CredentialForm<JiraCredentialJson>
              formBody={
                <>
                  <TextFormField name="jira_user_email" label="Username:" />
                  <TextFormField
                    name="jira_api_token"
                    label="Access Token:"
                    type="password"
                  />
                </>
              }
              validationSchema={Yup.object().shape({
                jira_user_email: Yup.string().required(
                  "Please enter your username on Jira"
                ),
                jira_api_token: Yup.string().required(
                  "Please enter your Jira access token"
                ),
              })}
              initialValues={{
                jira_user_email: "",
                jira_api_token: "",
              }}
              onSubmit={(isSuccess) => {
                if (isSuccess) {
                  refreshCredentials();
                }
              }}
            />
          </Card>
          <Title className="mb-2 mt-6 ml-auto mr-auto">Server</Title>
          <Card className="mt-4">
            <CredentialForm<JiraServerCredentialJson>
              formBody={
                <>
                  <TextFormField
                    name="jira_api_token"
                    label="Personal Access Token:"
                    type="password"
                  />
                </>
              }
              validationSchema={Yup.object().shape({
                jira_api_token: Yup.string().required(
                  "Please enter your Jira personal access token"
                ),
              })}
              initialValues={{
                jira_api_token: "",
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

      {/* TODO: make this periodic */}
      <Title className="mb-2 mt-6 ml-auto mr-auto">
        Step 2: Which spaces do you want to make searchable?
      </Title>
      {jiraCredential ? (
        <>
          {" "}
          <Text className="mb-4">
            Specify any link to a Jira page below and click &quot;Index&quot; to
            Index. Based on the provided link, we will index the ENTIRE PROJECT,
            not just the specified page. For example, entering{" "}
            <i>
              https://danswer.atlassian.net/jira/software/projects/DAN/boards/1
            </i>{" "}
            and clicking the Index button will index the whole <i>DAN</i> Jira
            project.
          </Text>
          {jiraConnectorIndexingStatuses.length > 0 && (
            <>
              <Text className="mb-2">
                We pull the latest pages and comments from each space listed
                below every <b>10</b> minutes.
              </Text>
              <div className="mb-2">
                <ConnectorsTable<
                  JiraConfig,
                  JiraCredentialJson | JiraServerCredentialJson
                >
                  connectorIndexingStatuses={jiraConnectorIndexingStatuses}
                  liveCredential={jiraCredential}
                  getCredential={(credential) => {
                    return (
                      <div>
                        <p>{credential.credential_json.jira_api_token}</p>
                      </div>
                    );
                  }}
                  onCredentialLink={async (connectorId) => {
                    if (jiraCredential) {
                      await linkCredential(connectorId, jiraCredential.id);
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
                            href={connectorConfig.jira_project_url}
                          >
                            {connectorConfig.jira_project_url}
                          </a>
                        );
                      },
                    },
                    {
                      header: "Disable comments from users",
                      key: "comment_email_blacklist",
                      getValue: (ccPairStatus) => {
                        const connectorConfig =
                          ccPairStatus.connector.connector_specific_config;
                        return connectorConfig.comment_email_blacklist &&
                          connectorConfig.comment_email_blacklist.length > 0
                          ? connectorConfig.comment_email_blacklist.join(", ")
                          : "";
                      },
                    },
                  ]}
                  onUpdate={() =>
                    mutate("/api/manage/admin/connector/indexing-status")
                  }
                />
              </div>
              <Divider />
            </>
          )}
          <Card className="mt-4">
            <h2 className="font-bold mb-3">Add a New Project</h2>
            <ConnectorForm<JiraConfig>
              nameBuilder={(values) =>
                `JiraConnector-${values.jira_project_url}`
              }
              ccPairNameBuilder={(values) =>
                extractJiraProject(values.jira_project_url)
              }
              credentialId={jiraCredential.id}
              source="jira"
              inputType="poll"
              formBody={
                <>
                  <TextFormField
                    name="jira_project_url"
                    label="Jira Project URL:"
                  />
                </>
              }
              formBodyBuilder={(values) => {
                return (
                  <>
                    <Divider />
                    {TextArrayFieldBuilder({
                      name: "comment_email_blacklist",
                      label: "Disable comments from users:",
                      subtext: `
                      This is generally useful to ignore certain bots. Add user emails which comments should NOT be indexed.`,
                    })(values)}
                  </>
                );
              }}
              validationSchema={Yup.object().shape({
                jira_project_url: Yup.string().required(
                  "Please enter any link to your jira project e.g. https://danswer.atlassian.net/jira/software/projects/DAN/boards/1"
                ),
                comment_email_blacklist: Yup.array()
                  .of(Yup.string().required("Emails names must be strings"))
                  .required(),
              })}
              initialValues={{
                jira_project_url: "",
                comment_email_blacklist: [],
              }}
              refreshFreq={10 * 60} // 10 minutes
            />
          </Card>
        </>
      ) : (
        <>
          <Text>
            Please provide your access token in Step 1 first! Once done with
            that, you can then specify which Jira projects you want to make
            searchable.
          </Text>
        </>
      )}
    </>
  );
};

export default function Page() {
  return (
    <div className="mx-auto container">
      <AdminPageTitle icon={<JiraIcon size={32} />} title="Jira" />

      <Main />
    </div>
  );
}
