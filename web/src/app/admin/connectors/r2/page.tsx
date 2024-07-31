"use client";

import { AdminPageTitle } from "@/components/admin/Title";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import { R2Icon, S3Icon, TrashIcon } from "@/components/icons/icons";
import { LoadingAnimation } from "@/components/Loading";
import { ConnectorForm } from "@/components/admin/connectors/ConnectorForm";
import { CredentialForm } from "@/components/admin/connectors/CredentialForm";
import { TextFormField } from "@/components/admin/connectors/Field";
import { usePopup } from "@/components/admin/connectors/Popup";
import { ConnectorsTable } from "@/components/admin/connectors/table/ConnectorsTable";
import { adminDeleteCredential, linkCredential } from "@/lib/credential";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { ErrorCallout } from "@/components/ErrorCallout";
import { usePublicCredentials } from "@/lib/hooks";
import {
  ConnectorIndexingStatus,
  Credential,
  R2Config,
  R2CredentialJson,
} from "@/lib/types";
import { Card, Select, SelectItem, Text, Title } from "@tremor/react";
import useSWR, { useSWRConfig } from "swr";
import * as Yup from "yup";
import { useState } from "react";

const R2Main = () => {
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

  const r2ConnectorIndexingStatuses: ConnectorIndexingStatus<
    R2Config,
    R2CredentialJson
  >[] = connectorIndexingStatuses.filter(
    (connectorIndexingStatus) =>
      connectorIndexingStatus.connector.source === "r2"
  );

  const r2Credential: Credential<R2CredentialJson> | undefined =
    credentialsData.find(
      (credential) => credential.credential_json?.account_id
    );

  return (
    <>
      {popup}
      <Title className="mb-2 mt-6 ml-auto mr-auto">
        Step 1: Provide your access info
      </Title>
      {r2Credential ? (
        <>
          {" "}
          <div className="flex mb-1 text-sm">
            <p className="my-auto">Existing R2 Access Key ID: </p>
            <p className="ml-1 italic my-auto">
              {r2Credential.credential_json.r2_access_key_id}
            </p>
            {", "}
            <p className="ml-1 my-auto">Account ID: </p>
            <p className="ml-1 italic my-auto">
              {r2Credential.credential_json.account_id}
            </p>{" "}
            <button
              className="ml-1 hover:bg-hover rounded p-1"
              onClick={async () => {
                if (r2ConnectorIndexingStatuses.length > 0) {
                  setPopup({
                    type: "error",
                    message:
                      "Must delete all connectors before deleting credentials",
                  });
                  return;
                }
                await adminDeleteCredential(r2Credential.id);
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
            <ul className="list-disc mt-2 ml-4">
              <li>
                Provide your R2 Access Key ID, Secret Access Key, and Account ID
                for authentication.
              </li>
              <li>These credentials will be used to access your R2 buckets.</li>
            </ul>
          </Text>
          <Card className="mt-4">
            <CredentialForm<R2CredentialJson>
              formBody={
                <>
                  <TextFormField
                    name="r2_access_key_id"
                    label="R2 Access Key ID:"
                  />
                  <TextFormField
                    name="r2_secret_access_key"
                    label="R2 Secret Access Key:"
                  />
                  <TextFormField name="account_id" label="Account ID:" />
                </>
              }
              validationSchema={Yup.object().shape({
                r2_access_key_id: Yup.string().required(
                  "R2 Access Key ID is required"
                ),
                r2_secret_access_key: Yup.string().required(
                  "R2 Secret Access Key is required"
                ),
                account_id: Yup.string().required("Account ID is required"),
              })}
              initialValues={{
                r2_access_key_id: "",
                r2_secret_access_key: "",
                account_id: "",
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
        Step 2: Which R2 bucket do you want to make searchable?
      </Title>

      {r2ConnectorIndexingStatuses.length > 0 && (
        <>
          <Title className="mb-2 mt-6 ml-auto mr-auto">
            R2 indexing status
          </Title>
          <Text className="mb-2">
            The latest changes are fetched every 10 minutes.
          </Text>
          <div className="mb-2">
            <ConnectorsTable<R2Config, R2CredentialJson>
              includeName={true}
              connectorIndexingStatuses={r2ConnectorIndexingStatuses}
              liveCredential={r2Credential}
              getCredential={(credential) => {
                return <div></div>;
              }}
              onCredentialLink={async (connectorId) => {
                if (r2Credential) {
                  await linkCredential(connectorId, r2Credential.id);
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

      {r2Credential && (
        <>
          <Card className="mt-4">
            <h2 className="font-bold mb-3">Create Connection</h2>
            <Text className="mb-4">
              Press connect below to start the connection to your R2 bucket.
            </Text>
            <ConnectorForm<R2Config>
              nameBuilder={(values) => `R2Connector-${values.bucket_name}`}
              ccPairNameBuilder={(values) =>
                `R2Connector-${values.bucket_name}`
              }
              source="r2"
              inputType="poll"
              formBodyBuilder={(values) => (
                <div>
                  <TextFormField name="bucket_name" label="Bucket Name:" />
                  <TextFormField
                    name="prefix"
                    label="Path Prefix (optional):"
                  />
                </div>
              )}
              validationSchema={Yup.object().shape({
                bucket_type: Yup.string()
                  .oneOf(["r2"])
                  .required("Bucket type must be r2"),
                bucket_name: Yup.string().required(
                  "Please enter the name of the r2 bucket to index, e.g. my-test-bucket"
                ),
                prefix: Yup.string().default(""),
              })}
              initialValues={{
                bucket_type: "r2",
                bucket_name: "",
                prefix: "",
              }}
              refreshFreq={60 * 60 * 24} // 1 day
              credentialId={r2Credential.id}
            />
          </Card>
        </>
      )}
    </>
  );
};

export default function Page() {
  const [selectedStorage, setSelectedStorage] = useState<string>("s3");

  return (
    <div className="mx-auto container">
      {" "}
      <AdminPageTitle icon={<R2Icon size={32} />} title="R2 Storage" />
      <R2Main key={2} />
    </div>
  );
}
