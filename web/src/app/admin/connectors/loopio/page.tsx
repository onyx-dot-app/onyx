"use client";

import * as Yup from "yup";
import { LoopioIcon, TrashIcon } from "@/components/icons/icons";
import { TextFormField } from "@/components/admin/connectors/Field";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import { CredentialForm } from "@/components/admin/connectors/CredentialForm";
import {
  Credential,
  ConnectorIndexingStatus,
  LoopioConfig,
  LoopioCredentialJson,
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
    isValidating: isCredentialsValidating,
    error: credentialsError,
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

  const loopioConnectorIndexingStatuses: ConnectorIndexingStatus<
    LoopioConfig,
    LoopioCredentialJson
  >[] = connectorIndexingStatuses.filter(
    (connectorIndexingStatus) =>
      connectorIndexingStatus.connector.source === "loopio"
  );
  const loopioCredential: Credential<LoopioCredentialJson> | undefined =
    credentialsData.find(
      (credential) => credential.credential_json?.loopio_client_id
    );

  return (
    <>
      {popup}
      <p className="text-sm">
        This connector allows you to sync your Loopio Library Entries into
        Danswer
      </p>

      <h2 className="font-bold mb-2 mt-6 ml-auto mr-auto">
        Step 1: Provide your API Access info
      </h2>

      {loopioCredential ? (
        <>
          <div className="flex mb-1 text-sm">
            <p className="my-auto">Existing App Key Secret: </p>
            <p className="ml-1 italic my-auto max-w-md truncate">
              {loopioCredential.credential_json?.loopio_client_token}
            </p>
            <button
              className="ml-1 hover:bg-gray-700 rounded-full p-1"
              onClick={async () => {
                if (loopioConnectorIndexingStatuses.length > 0) {
                  setPopup({
                    type: "error",
                    message:
                      "Must delete all connectors before deleting credentials",
                  });
                  return;
                }
                await adminDeleteCredential(loopioCredential.id);
                refreshCredentials();
              }}
            >
              <TrashIcon />
            </button>
          </div>
        </>
      ) : (
        <>
          <div className="border-solid border-gray-600 border rounded-md p-6 mt-2">
            <CredentialForm<LoopioCredentialJson>
              formBody={
                <>
                  <TextFormField
                    name="loopio_subdomain"
                    label="Account Subdomain:"
                  />
                  <TextFormField name="loopio_client_id" label="App Key ID:" />
                  <TextFormField
                    name="loopio_client_token"
                    label="App Key Secret:"
                    type="password"
                  />
                </>
              }
              validationSchema={Yup.object().shape({
                loopio_subdomain: Yup.string().required(
                  "Please enter your Loopio Account subdomain"
                ),
                loopio_client_id: Yup.string().required(
                  "Please enter your Loopio App Key ID"
                ),
                loopio_client_token: Yup.string().required(
                  "Please enter your Loopio App Key Secret"
                ),
              })}
              initialValues={{
                loopio_subdomain: "",
                loopio_client_id: "",
                loopio_client_token: "",
              }}
              onSubmit={(isSuccess) => {
                if (isSuccess) {
                  refreshCredentials();
                }
              }}
            />
          </div>
        </>
      )}

      <h2 className="font-bold mt-6 ml-auto mr-auto">
        Step 2: Which Stack do you want to make searchable?
      </h2>
      <p className="text-sm mb-2">
        Leave this blank if you want to index all stacks.
      </p>

      {loopioConnectorIndexingStatuses.length > 0 && (
        <>
          <p className="text-sm mb-2">
            We pull the latest library entries every <b>24</b> hours.
          </p>
          <div className="mb-2">
            <ConnectorsTable<LoopioConfig, LoopioCredentialJson>
              connectorIndexingStatuses={loopioConnectorIndexingStatuses}
              liveCredential={loopioCredential}
              getCredential={(credential) =>
                credential.credential_json.loopio_client_id
              }
              specialColumns={[
                {
                  header: "Stack",
                  key: "loopio_stack_name",
                  getValue: (ccPairStatus) =>
                    ccPairStatus.connector.connector_specific_config
                      .loopio_stack_name || "All stacks",
                },
              ]}
              includeName={true}
              onUpdate={() =>
                mutate("/api/manage/admin/connector/indexing-status")
              }
              onCredentialLink={async (connectorId) => {
                if (loopioCredential) {
                  await linkCredential(connectorId, loopioCredential.id);
                  mutate("/api/manage/admin/connector/indexing-status");
                }
              }}
            />
          </div>
        </>
      )}

      {loopioCredential ? (
        <>
          <div className="border-solid border-gray-600 border rounded-md p-6 mt-4">
            <h2 className="font-bold mb-3">Create a new Loopio Connector</h2>
            <ConnectorForm<LoopioConfig>
              nameBuilder={(values) =>
                values?.loopio_stack_name
                  ? `LoopioConnector-${values.loopio_stack_name}-Stack`
                  : `LoopioConnector-AllStacks`
              }
              source="loopio"
              inputType="poll"
              formBody={
                <>
                  <TextFormField
                    name="loopio_stack_name"
                    label="[Optional] Loopio Stack name:"
                    subtext=" Must be exact match to the name in Library Management, leave this blank if you want to index all Stacks"
                  />
                </>
              }
              validationSchema={Yup.object().shape({
                loopio_stack_name: Yup.string(),
              })}
              initialValues={{
                loopio_stack_name: "",
              }}
              refreshFreq={60 * 60 * 24} // 24 hours
              credentialId={loopioCredential.id}
            />
          </div>
        </>
      ) : (
        <p className="text-sm">
          Please provide your API Access Info in Step 1 first! Once done with
          that, you can start indexing your Loopio library.
        </p>
      )}
    </>
  );
};

export default function Page() {
  return (
    <div className="mx-auto container">
      {" "}
      <div className="border-solid border-gray-600 border-b mb-4 pb-2 flex">
        <LoopioIcon size={32} />
        <h1 className="text-3xl font-bold pl-2">Loopio</h1>
      </div>
      <Main />
    </div>
  );
}
