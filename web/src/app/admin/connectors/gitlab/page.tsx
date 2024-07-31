"use client";

import * as Yup from "yup";
import { GitlabIcon, TrashIcon } from "@/components/icons/icons";
import { TextFormField } from "@/components/admin/connectors/Field";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import useSWR, { useSWRConfig } from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { ErrorCallout } from "@/components/ErrorCallout";
import {
  GitlabConfig,
  GitlabCredentialJson,
  Credential,
  ConnectorIndexingStatus,
} from "@/lib/types";
import { ConnectorForm } from "@/components/admin/connectors/ConnectorForm";
import { LoadingAnimation } from "@/components/Loading";
import { CredentialForm } from "@/components/admin/connectors/CredentialForm";
import { adminDeleteCredential, linkCredential } from "@/lib/credential";
import { ConnectorsTable } from "@/components/admin/connectors/table/ConnectorsTable";
import { usePublicCredentials } from "@/lib/hooks";
import { Card, Divider, Text, Title } from "@tremor/react";
import { AdminPageTitle } from "@/components/admin/Title";

const Main = () => {
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

  const gitlabConnectorIndexingStatuses: ConnectorIndexingStatus<
    GitlabConfig,
    GitlabCredentialJson
  >[] = connectorIndexingStatuses.filter(
    (connectorIndexingStatus) =>
      connectorIndexingStatus.connector.source === "gitlab"
  );
  const gitlabCredential: Credential<GitlabCredentialJson> | undefined =
    credentialsData.find(
      (credential) => credential.credential_json?.gitlab_access_token
    );

  return (
    <>
      <Title className="mb-2 mt-6 ml-auto mr-auto">
        Step 1: Provide your access token
      </Title>
      {gitlabCredential ? (
        <>
          {" "}
          <div className="flex mb-1 text-sm">
            <p className="my-auto">Existing Access Token: </p>
            <p className="ml-1 italic my-auto">
              {gitlabCredential.credential_json.gitlab_access_token}
            </p>{" "}
            <button
              className="ml-1 hover:bg-hover rounded p-1"
              onClick={async () => {
                await adminDeleteCredential(gitlabCredential.id);
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
            If you don&apos;t have an access token, read the guide{" "}
            <a
              className="text-blue-500"
              href="https://docs.danswer.dev/connectors/gitlab"
              target="_blank"
            >
              here
            </a>{" "}
            on how to get one from Gitlab.
          </Text>
          <Card className="mt-4">
            <CredentialForm<GitlabCredentialJson>
              formBody={
                <>
                  <Text>
                    If you are using GitLab Cloud, keep the default value below
                  </Text>
                  <TextFormField
                    name="gitlab_url"
                    label="GitLab URL:"
                    type="text"
                    placeholder="https://gitlab.com"
                  />

                  <TextFormField
                    name="gitlab_access_token"
                    label="Access Token:"
                    type="password"
                  />
                </>
              }
              validationSchema={Yup.object().shape({
                gitlab_url: Yup.string().default("https://gitlab.com"),
                gitlab_access_token: Yup.string().required(
                  "Please enter the access token for Gitlab"
                ),
              })}
              initialValues={{
                gitlab_access_token: "",
                gitlab_url: "https://gitlab.com",
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
        Step 2: Which repositories do you want to make searchable?
      </Title>

      {gitlabConnectorIndexingStatuses.length > 0 && (
        <>
          <Text className="mb-2">
            We pull the latest Pull Requests from each project listed below
            every <b>10</b> minutes.
          </Text>
          <div className="mb-2">
            <ConnectorsTable<GitlabConfig, GitlabCredentialJson>
              connectorIndexingStatuses={gitlabConnectorIndexingStatuses}
              liveCredential={gitlabCredential}
              getCredential={(credential) =>
                credential.credential_json.gitlab_access_token
              }
              onCredentialLink={async (connectorId) => {
                if (gitlabCredential) {
                  await linkCredential(connectorId, gitlabCredential.id);
                  mutate("/api/manage/admin/connector/indexing-status");
                }
              }}
              specialColumns={[
                {
                  header: "Project",
                  key: "project",
                  getValue: (ccPairStatus) => {
                    const connectorConfig =
                      ccPairStatus.connector.connector_specific_config;
                    return `${connectorConfig.project_owner}/${connectorConfig.project_name}`;
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

      {gitlabCredential ? (
        <Card className="mt-4">
          <h2 className="font-bold mb-3">Connect to a New Project</h2>
          <ConnectorForm<GitlabConfig>
            nameBuilder={(values) =>
              `GitlabConnector-${values.project_owner}/${values.project_name}`
            }
            ccPairNameBuilder={(values) =>
              `${values.project_owner}/${values.project_name}`
            }
            source="gitlab"
            inputType="poll"
            formBody={
              <>
                <TextFormField name="project_owner" label="Project Owner:" />
                <TextFormField name="project_name" label="Project Name:" />
              </>
            }
            validationSchema={Yup.object().shape({
              project_owner: Yup.string().required(
                "Please enter the owner of the project to index e.g. danswer-ai"
              ),
              project_name: Yup.string().required(
                "Please enter the name of the project to index e.g. danswer "
              ),
              include_mrs: Yup.boolean().required(),
              include_issues: Yup.boolean().required(),
            })}
            initialValues={{
              project_owner: "",
              project_name: "",
              include_mrs: true,
              include_issues: true,
            }}
            refreshFreq={10 * 60} // 10 minutes
            credentialId={gitlabCredential.id}
          />
        </Card>
      ) : (
        <Text>
          Please provide your access token in Step 1 first! Once done with that,
          you can then specify which Gitlab repositories you want to make
          searchable.
        </Text>
      )}
    </>
  );
};

export default function Page() {
  return (
    <div className="container mx-auto">
      <AdminPageTitle
        icon={<GitlabIcon size={32} />}
        title="Gitlab MRs + Issues"
      />

      <Main />
    </div>
  );
}
