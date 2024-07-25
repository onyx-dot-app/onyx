"use client";

import * as Yup from "yup";
import { ConfluenceIcon, TrashIcon } from "@/components/icons/icons";
import {
  BooleanFormField,
  TextFormField,
} from "@/components/admin/connectors/Field";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import { CredentialForm } from "@/components/admin/connectors/CredentialForm";
import {
  ConfluenceCredentialJson,
  ConfluenceConfig,
  ConnectorIndexingStatus,
  Credential,
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

const extractSpaceFromCloudUrl = (wikiUrl: string): string => {
  const parsedUrl = new URL(wikiUrl);
  const space = parsedUrl.pathname.split("/")[3];
  return space;
};

const extractSpaceFromDataCenterUrl = (wikiUrl: string): string => {
  const DISPLAY = "/display/";

  const parsedUrl = new URL(wikiUrl);
  const spaceSpecificSection = parsedUrl.pathname
    .split(DISPLAY)
    .slice(1)
    .join(DISPLAY);
  const space = spaceSpecificSection.split("/")[0];
  return space;
};

// Copied from the `extract_confluence_keys_from_url` function
const extractSpaceFromUrl = (wikiUrl: string): string | null => {
  try {
    if (
      wikiUrl.includes(".atlassian.net/wiki/spaces/") ||
      wikiUrl.includes(".jira.com/wiki/spaces/")
    ) {
      return extractSpaceFromCloudUrl(wikiUrl);
    }
    return extractSpaceFromDataCenterUrl(wikiUrl);
  } catch (e) {
    console.log("Failed to extract space from url", e);
    return null;
  }
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

  const confluenceConnectorIndexingStatuses: ConnectorIndexingStatus<
    ConfluenceConfig,
    ConfluenceCredentialJson
  >[] = connectorIndexingStatuses.filter(
    (connectorIndexingStatus) =>
      connectorIndexingStatus.connector.source === "confluence"
  );
  const confluenceCredential: Credential<ConfluenceCredentialJson> | undefined =
    credentialsData.find(
      (credential) => credential.credential_json?.confluence_access_token
    );

  return (
    <>
      {popup}
      <Title className="mb-2 mt-6 ml-auto mr-auto">
        Step 1: Provide your access token
      </Title>

      {confluenceCredential ? (
        <>
          <div className="flex mb-1 text-sm">
            {/* <div className="flex">
                <p className="my-auto">Existing Username: </p>
                <p className="ml-1 italic my-auto max-w-md truncate">
                  {confluenceCredential.credential_json?.confluence_username}
                </p>{" "}
              </div> */}
            <p className="my-auto">Existing Access Token: </p>
            <p className="ml-1 italic my-auto max-w-md truncate">
              {confluenceCredential.credential_json?.confluence_access_token}
            </p>
            <button
              className="ml-1 hover:bg-hover rounded p-1"
              onClick={async () => {
                if (confluenceConnectorIndexingStatuses.length > 0) {
                  setPopup({
                    type: "error",
                    message:
                      "Must delete all connectors before deleting credentials",
                  });
                  return;
                }
                await adminDeleteCredential(confluenceCredential.id);
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
            To use the Confluence connector, first follow the guide{" "}
            <a
              className="text-link"
              href="https://docs.danswer.dev/connectors/confluence#setting-up"
              target="_blank"
            >
              here
            </a>{" "}
            to generate an Access Token.
          </Text>
          <Card className="mt-4">
            <CredentialForm<ConfluenceCredentialJson>
              formBody={
                <>
                  <TextFormField name="confluence_username" label="Username:" />
                  <TextFormField
                    name="confluence_access_token"
                    label="Access Token:"
                    type="password"
                  />
                </>
              }
              validationSchema={Yup.object().shape({
                confluence_username: Yup.string().required(
                  "Please enter your username on Confluence"
                ),
                confluence_access_token: Yup.string().required(
                  "Please enter your Confluence access token"
                ),
              })}
              initialValues={{
                confluence_username: "",
                confluence_access_token: "",
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

      <h2 className="font-bold mb-2 mt-6 ml-auto mr-auto">
        Step 2: Which spaces do you want to make searchable?
      </h2>
      {confluenceCredential ? (
        <>
          <p className="text-sm mb-4">
            Specify any link to a Confluence page below and click
            &quot;Index&quot; to Index. Based on the provided link, we will
            index either the entire page and its subpages OR the entire space.
            For example, entering{" "}
            <i>
              https://danswer.atlassian.net/wiki/spaces/Engineering/overview
            </i>{" "}
            and clicking the Index button will index the whole{" "}
            <i>Engineering</i> Confluence space, but entering
            https://danswer.atlassian.net/wiki/spaces/Engineering/pages/164331/example+page
            will index that page&apos;s children (and optionally, itself). Use
            the checkbox below to determine whether or not to index the parent
            page in addition to its children.
          </p>

          {confluenceConnectorIndexingStatuses.length > 0 && (
            <>
              <p className="text-sm mb-2">
                We pull the latest pages and comments from each space listed
                below every <b>10</b> minutes.
              </p>
              <div className="mb-2">
                <ConnectorsTable<ConfluenceConfig, ConfluenceCredentialJson>
                  connectorIndexingStatuses={
                    confluenceConnectorIndexingStatuses
                  }
                  liveCredential={confluenceCredential}
                  getCredential={(credential) => {
                    return (
                      <div>
                        <p>
                          {credential.credential_json.confluence_access_token}
                        </p>
                      </div>
                    );
                  }}
                  onCredentialLink={async (connectorId) => {
                    if (confluenceCredential) {
                      await linkCredential(
                        connectorId,
                        confluenceCredential.id
                      );
                      mutate("/api/manage/admin/connector/indexing-status");
                    }
                  }}
                  specialColumns={[
                    {
                      header: "Url",
                      key: "url",
                      getValue: (ccPairStatus) => (
                        <a
                          className="text-blue-500"
                          href={
                            ccPairStatus.connector.connector_specific_config
                              .wiki_page_url
                          }
                        >
                          {
                            ccPairStatus.connector.connector_specific_config
                              .wiki_page_url
                          }
                        </a>
                      ),
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
            <h2 className="font-bold mb-3">Add a New Space or Page</h2>
            <ConnectorForm<ConfluenceConfig>
              nameBuilder={(values) =>
                `ConfluenceConnector-${values.wiki_page_url}`
              }
              ccPairNameBuilder={(values) =>
                extractSpaceFromUrl(values.wiki_page_url)
              }
              source="confluence"
              inputType="poll"
              formBody={
                <>
                  <TextFormField name="wiki_page_url" label="Confluence URL:" />
                  <BooleanFormField
                    name="index_origin"
                    label="(For pages) Index the page itself"
                  />
                </>
              }
              validationSchema={Yup.object().shape({
                wiki_page_url: Yup.string().required(
                  "Please enter any link to a Confluence space or Page e.g. https://danswer.atlassian.net/wiki/spaces/Engineering/overview"
                ),
                index_origin: Yup.boolean(),
              })}
              initialValues={{
                wiki_page_url: "",
                index_origin: true,
              }}
              refreshFreq={10 * 60} // 10 minutes
              credentialId={confluenceCredential.id}
            />
          </Card>
        </>
      ) : (
        <Text>
          Please provide your access token in Step 1 first! Once done with that,
          you can then specify which Confluence spaces you want to make
          searchable.
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

      <AdminPageTitle icon={<ConfluenceIcon size={32} />} title="Confluence" />

      <Main />
    </div>
  );
}
