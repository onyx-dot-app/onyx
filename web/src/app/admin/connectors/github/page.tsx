"use client";

import * as Yup from "yup";
import { GithubIcon, TrashIcon } from "@/components/icons/icons";
import { TextFormField } from "@/components/admin/connectors/Field";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import useSWR, { useSWRConfig } from "swr";
import { fetcher } from "@/lib/fetcher";
import {
  Connector,
  GithubConfig,
  GithubCredentialJson,
  Credential,
} from "@/lib/types";
import { GithubConnectorsTable } from "./ConnectorsTable";
import { ConnectorForm } from "@/components/admin/connectors/ConnectorForm";
import { LoadingAnimation } from "@/components/Loading";
import { CredentialForm } from "@/components/admin/connectors/CredentialForm";
import { deleteCredential, linkCredential } from "@/lib/credential";

const Main = () => {
  const { mutate } = useSWRConfig();
  const {
    data: connectorsData,
    isLoading: isConnectorsLoading,
    error: isConnectorsError,
  } = useSWR<Connector<GithubConfig>[]>("/api/admin/connector", fetcher);

  const {
    data: credentialsData,
    isLoading: isCredentialsLoading,
    isValidating: isCredentialsValidating,
    error: isCredentialsError,
  } = useSWR<Credential<GithubCredentialJson>[]>(
    "/api/admin/credential",
    fetcher
  );

  if (isConnectorsLoading || isCredentialsLoading || isCredentialsValidating) {
    return <LoadingAnimation text="Loading" />;
  }

  if (isConnectorsError || !connectorsData) {
    return <div>Failed to load connectors</div>;
  }

  if (isCredentialsError || !credentialsData) {
    return <div>Failed to load credentials</div>;
  }

  const githubConnectors = connectorsData.filter(
    (connector) => connector.source === "github"
  );
  const githubCredential = credentialsData.filter(
    (credential) => credential.credential_json?.github_token
  )[0];

  return (
    <>
      <h2 className="font-bold mb-2 mt-6 ml-auto mr-auto">
        Step 1: Provide your access token
      </h2>
      {githubCredential ? (
        <>
          {" "}
          <div className="flex mb-1 text-sm">
            <p className="my-auto">Existing Access Token: </p>
            <p className="ml-1 italic my-auto">
              {githubCredential.credential_json.github_token}
            </p>{" "}
            <button
              className="ml-1 hover:bg-gray-700 rounded-full p-1"
              onClick={async () => {
                await deleteCredential(githubCredential.id);
                mutate("/api/admin/credential");
              }}
            >
              <TrashIcon />
            </button>
          </div>
        </>
      ) : (
        <>
          <p className="text-sm">
            If you don't have an access token, read the guide{" "}
            <a
              className="text-blue-500"
              href="https://docs.danswer.dev/connectors/github"
            >
              here
            </a>{" "}
            on how to get one from Github.
          </p>
          <div className="border-solid border-gray-600 border rounded-md p-6 mt-2">
            <CredentialForm<GithubCredentialJson>
              formBody={
                <>
                  <TextFormField
                    name="github_token"
                    label="Access Token:"
                    type="password"
                  />
                </>
              }
              validationSchema={Yup.object().shape({
                github_token: Yup.string().required(
                  "Please enter the access token for Github"
                ),
              })}
              initialValues={{
                github_token: "",
              }}
              onSubmit={(isSuccess) => {
                if (isSuccess) {
                  mutate("/api/admin/credential");
                }
              }}
            />
          </div>
        </>
      )}

      <h2 className="font-bold mb-2 mt-6 ml-auto mr-auto">
        Step 2: Which repositories do you want to make searchable?
      </h2>

      {connectorsData.length > 0 && (
        <>
          <p className="text-sm mb-2">
            We pull the latest Pull Requests from each repository listed below
            every <b>10</b> minutes.
          </p>
          <div className="mb-2">
            <GithubConnectorsTable
              connectors={githubConnectors}
              liveCredential={githubCredential}
              onDelete={() => mutate("/api/admin/connector")}
              onCredentialLink={async (connectorId) => {
                if (githubCredential) {
                  await linkCredential(connectorId, githubCredential.id);
                  mutate("/api/admin/connector");
                }
              }}
            />
          </div>
        </>
      )}

      <div className="border-solid border-gray-600 border rounded-md p-6 mt-2">
        <h2 className="font-bold mb-3">Connect to a new repository</h2>
        <ConnectorForm<GithubConfig>
          nameBuilder={(values) =>
            `GithubConnector-${values.repo_owner}/${values.repo_name}`
          }
          source="github"
          inputType="load_state"
          formBody={
            <>
              <TextFormField name="repo_owner" label="Repository Owner:" />
              <TextFormField name="repo_name" label="Repository Name:" />
            </>
          }
          validationSchema={Yup.object().shape({
            repo_owner: Yup.string().required(
              "Please enter the owner of the repository to index e.g. danswer-ai"
            ),
            repo_name: Yup.string().required(
              "Please enter the name of the repository to index e.g. danswer "
            ),
          })}
          initialValues={
            connectorsData.filter(
              (connector) => connector.name === "GithubConnector"
            )[0]?.connector_specific_config || {
              repo_owner: "",
              repo_name: "",
            }
          }
          onSubmit={async (isSuccess, responseJson) => {
            if (isSuccess && responseJson) {
              await linkCredential(responseJson.id, githubCredential.id);
              mutate("/api/admin/connector");
            }
          }}
        />
      </div>
    </>
  );
};

export default function Page() {
  return (
    <div className="container mx-auto">
      <div className="mb-4">
        <HealthCheckBanner />
      </div>
      <div className="border-solid border-gray-600 border-b mb-4 pb-2 flex">
        <GithubIcon size="32" />
        <h1 className="text-3xl font-bold pl-2">Github PRs</h1>
      </div>
      <Main />
    </div>
  );
}
