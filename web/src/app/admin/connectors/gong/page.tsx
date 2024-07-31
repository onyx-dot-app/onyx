"use client";

import * as Yup from "yup";
import { GongIcon, TrashIcon } from "@/components/icons/icons";
import {
  TextFormField,
  TextArrayFieldBuilder,
} from "@/components/admin/connectors/Field";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import { CredentialForm } from "@/components/admin/connectors/CredentialForm";
import {
  Credential,
  ConnectorIndexingStatus,
  GongConfig,
  GongCredentialJson,
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

  const gongConnectorIndexingStatuses: ConnectorIndexingStatus<
    GongConfig,
    GongCredentialJson
  >[] = connectorIndexingStatuses.filter(
    (connectorIndexingStatus) =>
      connectorIndexingStatus.connector.source === "gong"
  );
  const gongCredential: Credential<GongCredentialJson> | undefined =
    credentialsData.find(
      (credential) => credential.credential_json?.gong_access_key
    );

  return (
    <>
      {popup}
      <Text>
        This connector allows you to sync all your Gong Transcripts into
        Danswer. More details on how to setup the Gong connector can be found in{" "}
        <a
          className="text-link"
          href="https://docs.danswer.dev/connectors/gong"
          target="_blank"
        >
          this guide.
        </a>
      </Text>

      <Title className="mb-2 mt-6 ml-auto mr-auto">
        Step 1: Provide your API Access info
      </Title>

      {gongCredential ? (
        <>
          <div className="flex mb-1 text-sm">
            <p className="my-auto">Existing Access Key Secret: </p>
            <p className="ml-1 italic my-auto max-w-md truncate">
              {gongCredential.credential_json?.gong_access_key_secret}
            </p>
            <button
              className="ml-1 hover:bg-hover rounded p-1"
              onClick={async () => {
                if (gongConnectorIndexingStatuses.length > 0) {
                  setPopup({
                    type: "error",
                    message:
                      "Must delete all connectors before deleting credentials",
                  });
                  return;
                }
                await adminDeleteCredential(gongCredential.id);
                refreshCredentials();
              }}
            >
              <TrashIcon />
            </button>
          </div>
        </>
      ) : (
        <>
          <Card className="mt-4">
            <CredentialForm<GongCredentialJson>
              formBody={
                <>
                  <TextFormField name="gong_access_key" label="Access Key:" />
                  <TextFormField
                    name="gong_access_key_secret"
                    label="Access Key Secret:"
                    type="password"
                  />
                </>
              }
              validationSchema={Yup.object().shape({
                gong_access_key: Yup.string().required(
                  "Please enter your Gong Access Key"
                ),
                gong_access_key_secret: Yup.string().required(
                  "Please enter your Gong Access Key Secret"
                ),
              })}
              initialValues={{
                gong_access_key: "",
                gong_access_key_secret: "",
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
        Step 2: Which Workspaces do you want to make searchable?
      </Title>

      {gongConnectorIndexingStatuses.length > 0 && (
        <>
          <Text className="mb-2">
            We pull the latest transcript every <b>10</b> minutes.
          </Text>
          <div className="mb-2">
            <ConnectorsTable<GongConfig, GongCredentialJson>
              connectorIndexingStatuses={gongConnectorIndexingStatuses}
              liveCredential={gongCredential}
              getCredential={(credential) =>
                credential.credential_json.gong_access_key
              }
              specialColumns={[
                {
                  header: "Workspaces",
                  key: "workspaces",
                  getValue: (ccPairStatus) =>
                    ccPairStatus.connector.connector_specific_config
                      .workspaces &&
                    ccPairStatus.connector.connector_specific_config.workspaces
                      .length > 0
                      ? ccPairStatus.connector.connector_specific_config.workspaces.join(
                          ", "
                        )
                      : "",
                },
              ]}
              includeName={true}
              onUpdate={() =>
                mutate("/api/manage/admin/connector/indexing-status")
              }
              onCredentialLink={async (connectorId) => {
                if (gongCredential) {
                  await linkCredential(connectorId, gongCredential.id);
                  mutate("/api/manage/admin/connector/indexing-status");
                }
              }}
            />
          </div>
          <Divider />
        </>
      )}

      {gongCredential ? (
        <>
          <Card className="mt-4">
            <h2 className="font-bold mb-3">Create a new Gong Connector</h2>
            <ConnectorForm<GongConfig>
              nameBuilder={(values) =>
                values.workspaces
                  ? `GongConnector-${values.workspaces.join("_")}`
                  : `GongConnector-All`
              }
              source="gong"
              inputType="poll"
              formBodyBuilder={TextArrayFieldBuilder({
                name: "workspaces",
                label: "Workspaces:",
                subtext:
                  "Specify 0 or more workspaces to index. Provide the workspace ID or the EXACT workspace " +
                  "name from Gong. If no workspaces are specified, transcripts from all workspaces will " +
                  "be indexed.",
              })}
              validationSchema={Yup.object().shape({
                workspaces: Yup.array().of(
                  Yup.string().required("Workspace names must be strings")
                ),
              })}
              initialValues={{
                workspaces: [],
              }}
              refreshFreq={10 * 60} // 10 minutes
              credentialId={gongCredential.id}
            />
          </Card>
        </>
      ) : (
        <Text>
          Please provide your API Access Info in Step 1 first! Once done with
          that, you can then start indexing all your Gong transcripts.
        </Text>
      )}
    </>
  );
};

export default function Page() {
  return (
    <div className="mx-auto container">
      <AdminPageTitle icon={<GongIcon size={32} />} title="Gong" />

      <Main />
    </div>
  );
}
