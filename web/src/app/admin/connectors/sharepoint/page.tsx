"use client";

import * as Yup from "yup";
import { TrashIcon, SharepointIcon } from "@/components/icons/icons"; // Make sure you have a Document360 icon
import { errorHandlingFetcher } from "@/lib/fetcher";
import { ErrorCallout } from "@/components/ErrorCallout";
import useSWR, { useSWRConfig } from "swr";
import { LoadingAnimation } from "@/components/Loading";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import {
  SharepointConfig,
  SharepointCredentialJson,
  ConnectorIndexingStatus,
  Credential,
} from "@/lib/types"; // Modify or create these types as required
import { adminDeleteCredential, linkCredential } from "@/lib/credential";
import { CredentialForm } from "@/components/admin/connectors/CredentialForm";
import {
  TextFormField,
  TextArrayFieldBuilder,
} from "@/components/admin/connectors/Field";
import { ConnectorsTable } from "@/components/admin/connectors/table/ConnectorsTable";
import { ConnectorForm } from "@/components/admin/connectors/ConnectorForm";
import { usePublicCredentials } from "@/lib/hooks";
import { AdminPageTitle } from "@/components/admin/Title";
import { Card, Text, Title } from "@tremor/react";

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

  const sharepointConnectorIndexingStatuses: ConnectorIndexingStatus<
    SharepointConfig,
    SharepointCredentialJson
  >[] = connectorIndexingStatuses.filter(
    (connectorIndexingStatus) =>
      connectorIndexingStatus.connector.source === "sharepoint"
  );

  const sharepointCredential: Credential<SharepointCredentialJson> | undefined =
    credentialsData.find(
      (credential) => credential.credential_json?.sp_client_id
    );

  return (
    <>
      <Text>
        The Sharepoint connector allows you to index and search through your
        Sharepoint files. Once setup, your Word documents, Excel files,
        PowerPoint presentations, OneNote notebooks, PDFs, and uploaded files
        will be queryable within Danswer.
      </Text>

      <Title className="mb-2 mt-6 ml-auto mr-auto">
        Step 1: Provide Sharepoint credentials
      </Title>
      {sharepointCredential ? (
        <>
          <div className="flex mb-1 text-sm">
            <Text className="my-auto">Existing Azure AD Client ID: </Text>
            <Text className="ml-1 italic my-auto">
              {sharepointCredential.credential_json.sp_client_id}
            </Text>
            <button
              className="ml-1 hover:bg-hover rounded p-1"
              onClick={async () => {
                await adminDeleteCredential(sharepointCredential.id);
                refreshCredentials();
              }}
            >
              <TrashIcon />
            </button>
          </div>
        </>
      ) : (
        <>
          <Text className="mb-2">
            As a first step, please provide Application (client) ID, Directory
            (tenant) ID, and Client Secret. You can follow the guide{" "}
            <a
              target="_blank"
              href="https://docs.danswer.dev/connectors/sharepoint"
              className="text-link"
            >
              here
            </a>{" "}
            to create an Azure AD application and obtain these values.
          </Text>
          <Card className="mt-2">
            <CredentialForm<SharepointCredentialJson>
              formBody={
                <>
                  <TextFormField
                    name="sp_client_id"
                    label="Application (client) ID:"
                  />
                  <TextFormField
                    name="sp_directory_id"
                    label="Directory (tenant) ID:"
                  />
                  <TextFormField
                    name="sp_client_secret"
                    label="Client Secret:"
                    type="password"
                  />
                </>
              }
              validationSchema={Yup.object().shape({
                sp_client_id: Yup.string().required(
                  "Please enter your Application (client) ID"
                ),
                sp_directory_id: Yup.string().required(
                  "Please enter your Directory (tenant) ID"
                ),
                sp_client_secret: Yup.string().required(
                  "Please enter your Client Secret"
                ),
              })}
              initialValues={{
                sp_client_id: "",
                sp_directory_id: "",
                sp_client_secret: "",
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
        Step 2: Manage Sharepoint Connector
      </Title>

      {sharepointConnectorIndexingStatuses.length > 0 && (
        <>
          <Text className="mb-2">
            The latest state of your Word documents, Excel files, PowerPoint
            presentations, OneNote notebooks, PDFs, and uploaded files are
            fetched every 10 minutes.
          </Text>
          <div className="mb-2">
            <ConnectorsTable<SharepointConfig, SharepointCredentialJson>
              connectorIndexingStatuses={sharepointConnectorIndexingStatuses}
              liveCredential={sharepointCredential}
              getCredential={(credential) =>
                credential.credential_json.sp_directory_id
              }
              onUpdate={() =>
                mutate("/api/manage/admin/connector/indexing-status")
              }
              onCredentialLink={async (connectorId) => {
                if (sharepointCredential) {
                  await linkCredential(connectorId, sharepointCredential.id);
                  mutate("/api/manage/admin/connector/indexing-status");
                }
              }}
              specialColumns={[
                {
                  header: "Connectors",
                  key: "connectors",
                  getValue: (ccPairStatus) => {
                    const connectorConfig =
                      ccPairStatus.connector.connector_specific_config;
                    return `${connectorConfig.sites}`;
                  },
                },
              ]}
              includeName
            />
          </div>
        </>
      )}

      {sharepointCredential ? (
        <Card className="mt-4">
          <ConnectorForm<SharepointConfig>
            nameBuilder={(values) =>
              values.sites && values.sites.length > 0
                ? `Sharepoint-${values.sites.join("-")}`
                : "Sharepoint"
            }
            ccPairNameBuilder={(values) =>
              values.sites && values.sites.length > 0
                ? `Sharepoint-${values.sites.join("-")}`
                : "Sharepoint"
            }
            source="sharepoint"
            inputType="poll"
            // formBody={<></>}
            formBodyBuilder={TextArrayFieldBuilder({
              name: "sites",
              label: "Sites:",
              subtext: (
                <>
                  <br />
                  <ul>
                    <li>
                      • If no sites are specified, all sites in your
                      organization will be indexed (Sites.Read.All permission
                      required).
                    </li>
                    <li>
                      • Specifying
                      &apos;https://danswerai.sharepoint.com/sites/support&apos;
                      for example will only index documents within this site.
                    </li>
                    <li>
                      • Specifying
                      &apos;https://danswerai.sharepoint.com/sites/support/subfolder&apos;
                      for example will only index documents within this folder.
                    </li>
                  </ul>
                </>
              ),
            })}
            validationSchema={Yup.object().shape({
              sites: Yup.array()
                .of(Yup.string().required("Site names must be strings"))
                .required(),
            })}
            initialValues={{
              sites: [],
            }}
            credentialId={sharepointCredential.id}
            refreshFreq={10 * 60} // 10 minutes
          />
        </Card>
      ) : (
        <Text>
          Please provide all Azure info in Step 1 first! Once you&apos;re done
          with that, you can then specify which Sharepoint sites you want to
          make searchable.
        </Text>
      )}
    </>
  );
};

export default function Page() {
  return (
    <div className="mx-auto container">
      <AdminPageTitle icon={<SharepointIcon size={32} />} title="Sharepoint" />

      <MainSection />
    </div>
  );
}
