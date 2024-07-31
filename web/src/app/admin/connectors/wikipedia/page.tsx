"use client";

import * as Yup from "yup";
import { WikipediaIcon, TrashIcon } from "@/components/icons/icons";
import {
  TextArrayField,
  TextArrayFieldBuilder,
  TextFormField,
} from "@/components/admin/connectors/Field";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import { CredentialForm } from "@/components/admin/connectors/CredentialForm";
import {
  WikipediaCredentialJson,
  WikipediaConfig,
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

  const wikipediaConnectorIndexingStatuses: ConnectorIndexingStatus<
    WikipediaConfig,
    WikipediaCredentialJson
  >[] = connectorIndexingStatuses.filter(
    (connectorIndexingStatus) =>
      connectorIndexingStatus.connector.source === "wikipedia"
  );
  const wikipediaCredential: Credential<WikipediaCredentialJson> | undefined =
    credentialsData.find((credential) => true);

  return (
    <>
      {popup}
      {wikipediaConnectorIndexingStatuses.length > 0 && (
        <>
          <Title className="mb-2 mt-6 ml-auto mr-auto">
            Wikipedia indexing status
          </Title>
          <Text className="mb-2">
            The latest page, chapter, book and shelf changes are fetched every
            10 minutes.
          </Text>
          <div className="mb-2">
            <ConnectorsTable<WikipediaConfig, WikipediaCredentialJson>
              connectorIndexingStatuses={wikipediaConnectorIndexingStatuses}
              liveCredential={wikipediaCredential}
              getCredential={(credential) => {
                return <div></div>;
              }}
              onCredentialLink={async (connectorId) => {
                if (wikipediaCredential) {
                  await linkCredential(connectorId, wikipediaCredential.id);
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

      {wikipediaCredential && (
        <>
          <Card className="mt-4">
            <h2 className="font-bold mb-3">Create Connection</h2>
            <Text className="mb-4">
              Press connect below to start the connection to your Wikipedia
              instance.
            </Text>
            <ConnectorForm<WikipediaConfig>
              nameBuilder={(values) =>
                `WikipediaConnector-${values.connector_name}`
              }
              ccPairNameBuilder={(values) =>
                `WikipediaConnector-${values.connector_name}`
              }
              source="wikipedia"
              inputType="poll"
              formBodyBuilder={(values) => (
                <div>
                  <TextFormField
                    name="connector_name"
                    label="Connector Name:"
                  />
                  <TextFormField
                    name="language_code"
                    label="Wikipedia Site Language Code (e.g. 'en', 'sp', etc...):"
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
                      "Specify 0 or more names of categories to index. These are pages" +
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
                  "Please enter a name for your Wikipedia connector."
                ),
                language_code: Yup.string().default("en"),
                categories: Yup.array().of(
                  Yup.string().required(
                    "Please enter categories to index from your Wikipedia site"
                  )
                ),
                pages: Yup.array().of(
                  Yup.string().required(
                    "Please enter pages to index from your Wikipedia site"
                  )
                ),
                recurse_depth: Yup.number().required(
                  "Please enter the recursion depth for your Wikipedia site."
                ),
              })}
              initialValues={{
                connector_name: "",
                language_code: "en",
                categories: [],
                pages: [],
                recurse_depth: 0,
              }}
              refreshFreq={10 * 60} // 10 minutes
              credentialId={wikipediaCredential.id}
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
      <AdminPageTitle icon={<WikipediaIcon size={32} />} title="Wikipedia" />

      <Main />
    </div>
  );
}
