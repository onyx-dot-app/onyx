"use client";

import * as Yup from "yup";
import { MediaWikiIcon, TrashIcon } from "@/components/icons/icons";
import {
  TextArrayField,
  TextArrayFieldBuilder,
  TextFormField,
} from "@/components/admin/connectors/Field";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import { CredentialForm } from "@/components/admin/connectors/CredentialForm";
import {
  MediaWikiCredentialJson,
  MediaWikiConfig,
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
import { AdminPageTitle } from "@/components/admin/Title";
import { Card, Text, Title } from "@tremor/react";

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

  const mediawikiConnectorIndexingStatuses: ConnectorIndexingStatus<
    MediaWikiConfig,
    MediaWikiCredentialJson
  >[] = connectorIndexingStatuses.filter(
    (connectorIndexingStatus) =>
      connectorIndexingStatus.connector.source === "mediawiki"
  );
  const mediawikiCredential: Credential<MediaWikiCredentialJson> | undefined =
    credentialsData.find((credential) => true);

  return (
    <>
      {popup}
      {mediawikiConnectorIndexingStatuses.length > 0 && (
        <>
          <Title className="mb-2 mt-6 ml-auto mr-auto">
            MediaWiki indexing status
          </Title>
          <Text className="mb-2">
            The latest page, chapter, book and shelf changes are fetched every
            10 minutes.
          </Text>
          <div className="mb-2">
            <ConnectorsTable<MediaWikiConfig, MediaWikiCredentialJson>
              connectorIndexingStatuses={mediawikiConnectorIndexingStatuses}
              liveCredential={mediawikiCredential}
              getCredential={(credential) => {
                return <div></div>;
              }}
              onCredentialLink={async (connectorId) => {
                if (mediawikiCredential) {
                  await linkCredential(connectorId, mediawikiCredential.id);
                  mutate("/api/manage/admin/connector/indexing-status");
                }
              }}
              onUpdate={() =>
                mutate("/api/manage/admin/connector/indexing-status")
              }
            />
          </div>
        </>
      )}

      {mediawikiCredential && (
        <>
          <Card className="mt-4">
            <h2 className="font-bold mb-3">Create Connection</h2>
            <Text className="mb-4">
              Press connect below to start the connection to your MediaWiki
              instance.
            </Text>
            <ConnectorForm<MediaWikiConfig>
              nameBuilder={(values) =>
                `MediaWikiConnector-${values.connector_name}`
              }
              ccPairNameBuilder={(values) =>
                `MediaWikiConnector-${values.connector_name}`
              }
              source="mediawiki"
              inputType="poll"
              formBodyBuilder={(values) => (
                <div>
                  <TextFormField
                    name="connector_name"
                    label="Connector Name:"
                  />
                  <TextFormField name="hostname" label="MediaWiki Site URL:" />
                  <TextFormField
                    name="language_code"
                    label="MediaWiki Site Language Code (e.g. 'en', 'sp', etc...):"
                  />
                  {TextArrayFieldBuilder({
                    name: "pages",
                    label: "Pages to index:",
                    subtext:
                      "Specify 0 or more names of pages to index. Only specify the name of the page, not its url.",
                  })(values)}
                  {TextArrayFieldBuilder({
                    name: "categories",
                    label: "Categories to index:",
                    subtext:
                      "Specify 0 or more names of categories to index. For most MediaWiki sites, these are pages" +
                      " with a name of the form 'Category: XYZ', that are lists of other pages/categories. Only" +
                      " specify the name of the category, not its url.",
                  })(values)}
                  <TextFormField
                    name="recurse_depth"
                    label="Recursion Depth:"
                    type="number"
                    subtext="When indexing categories that have sub-categories, this will determine how may levels to index. Specify 0 to only index the category itself (i.e. no recursion). Specify -1 for unlimited recursion depth. Note, that in some rare instances, a category might contain itself in its dependencies, which will cause an infinite loop. Only use -1 if you confident that this will not happen."
                  />
                </div>
              )}
              validationSchema={Yup.object().shape({
                connector_name: Yup.string().required(
                  "Please enter a name for your MediaWiki connector."
                ),
                hostname: Yup.string().required(
                  "Please enter the base URL for your MediaWiki site"
                ),
                language_code: Yup.string().default("en"),
                categories: Yup.array().of(
                  Yup.string().required(
                    "Please enter categories to index from your MediaWiki site"
                  )
                ),
                pages: Yup.array().of(
                  Yup.string().required(
                    "Please enter pages to index from your MediaWiki site"
                  )
                ),
                recurse_depth: Yup.number().required(
                  "Please enter the recursion depth for your MediaWiki site."
                ),
              })}
              initialValues={{
                connector_name: "",
                hostname: "",
                language_code: "en",
                categories: [],
                pages: [],
                recurse_depth: 0,
              }}
              refreshFreq={10 * 60} // 10 minutes
              credentialId={mediawikiCredential.id}
            />
          </Card>
        </>
      )}
    </>
  );
};

export default function Page() {
  return (
    <div className="mx-auto container">
      <AdminPageTitle icon={<MediaWikiIcon size={32} />} title="MediaWiki" />

      <Main />
    </div>
  );
}
