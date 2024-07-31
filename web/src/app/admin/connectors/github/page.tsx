"use client";

import * as Yup from "yup";
import { GithubIcon, TrashIcon } from "@/components/icons/icons";
import {
  BooleanFormField,
  TextFormField,
} from "@/components/admin/connectors/Field";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import useSWR, { useSWRConfig } from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { ErrorCallout } from "@/components/ErrorCallout";
import {
  GithubConfig,
  GithubCredentialJson,
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

  const githubConnectorIndexingStatuses: ConnectorIndexingStatus<
    GithubConfig,
    GithubCredentialJson
  >[] = connectorIndexingStatuses.filter(
    (connectorIndexingStatus) =>
      connectorIndexingStatus.connector.source === "github"
  );
  const githubCredential: Credential<GithubCredentialJson> | undefined =
    credentialsData.find(
      (credential) => credential.credential_json?.github_access_token
    );

  return (
    <>
      <Title className="mb-2 mt-6 ml-auto mr-auto">
        Step 1: Provide your access token
      </Title>
      {githubCredential ? (
        <>
          {" "}
          <div className="flex mb-1 text-sm">
            <p className="my-auto">Existing Access Token: </p>
            <p className="ml-1 italic my-auto">
              {githubCredential.credential_json.github_access_token}
            </p>{" "}
            <button
              className="ml-1 hover:bg-hover rounded p-1"
              onClick={async () => {
                await adminDeleteCredential(githubCredential.id);
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
              href="https://docs.danswer.dev/connectors/github"
              target="_blank"
            >
              here
            </a>{" "}
            on how to get one from Github.
          </Text>
          <Card className="mt-4">
            <CredentialForm<GithubCredentialJson>
              formBody={
                <>
                  <TextFormField
                    name="github_access_token"
                    label="Access Token:"
                    type="password"
                  />
                </>
              }
              validationSchema={Yup.object().shape({
                github_access_token: Yup.string().required(
                  "Please enter the access token for Github"
                ),
              })}
              initialValues={{
                github_access_token: "",
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

      {githubConnectorIndexingStatuses.length > 0 && (
        <>
          <Text className="mb-2">
            We pull the latest Pull Requests and/or Issues from each repository
            listed below every <b>10</b> minutes.
          </Text>
          <div className="mb-2">
            <ConnectorsTable<GithubConfig, GithubCredentialJson>
              connectorIndexingStatuses={githubConnectorIndexingStatuses}
              liveCredential={githubCredential}
              getCredential={(credential) =>
                credential.credential_json.github_access_token
              }
              onCredentialLink={async (connectorId) => {
                if (githubCredential) {
                  await linkCredential(connectorId, githubCredential.id);
                  mutate("/api/manage/admin/connector/indexing-status");
                }
              }}
              specialColumns={[
                {
                  header: "Repository",
                  key: "repository",
                  getValue: (ccPairStatus) => {
                    const connectorConfig =
                      ccPairStatus.connector.connector_specific_config;
                    return `${connectorConfig.repo_owner}/${connectorConfig.repo_name}`;
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

      {githubCredential ? (
        <Card className="mt-4">
          <h2 className="font-bold mb-1">Connect to a New Repository</h2>

          <Text className="mb-4">
            The Github connector can index Pull Requests and Issues.
          </Text>

          <ConnectorForm<GithubConfig>
            nameBuilder={(values) =>
              `GithubConnector-${values.repo_owner}/${values.repo_name}`
            }
            ccPairNameBuilder={(values) =>
              `${values.repo_owner}/${values.repo_name}`
            }
            source="github"
            inputType="poll"
            formBody={
              <>
                <TextFormField name="repo_owner" label="Repository Owner:" />
                <TextFormField name="repo_name" label="Repository Name:" />
                <BooleanFormField
                  name="include_prs"
                  label="Include Pull Requests"
                  subtext="Index pull requests from this repository"
                />
                <BooleanFormField
                  name="include_issues"
                  label="Include Issues"
                  subtext="Index issues from this repository"
                />
              </>
            }
            validationSchema={Yup.object().shape({
              repo_owner: Yup.string().required(
                "Please enter the owner of the repository to index e.g. danswer-ai"
              ),
              repo_name: Yup.string().required(
                "Please enter the name of the repository to index e.g. danswer "
              ),
              include_prs: Yup.boolean().required(),
              include_issues: Yup.boolean().required(),
            })}
            validate={(values) => {
              if (values.include_prs || values.include_issues) {
                return {} as Record<string, string>;
              }
              return {
                include_issues:
                  "Please select at least one of Pull Requests or Issues",
              };
            }}
            initialValues={{
              repo_owner: "",
              repo_name: "",
              include_prs: true,
              include_issues: true,
            }}
            refreshFreq={10 * 60} // 10 minutes
            credentialId={githubCredential.id}
          />
        </Card>
      ) : (
        <Text>
          Please provide your access token in Step 1 first! Once done with that,
          you can then specify which Github repositories you want to make
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
        icon={<GithubIcon size={32} />}
        title="Github PRs + Issues"
      />

      <Main />
    </div>
  );
}
