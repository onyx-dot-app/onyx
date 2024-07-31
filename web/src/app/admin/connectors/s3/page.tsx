"use client";

import { AdminPageTitle } from "@/components/admin/Title";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import { S3Icon, TrashIcon } from "@/components/icons/icons";
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
  S3Config,
  S3CredentialJson,
} from "@/lib/types";
import { Card, Text, Title } from "@tremor/react";
import useSWR, { useSWRConfig } from "swr";
import * as Yup from "yup";
import { useState } from "react";

const S3Main = () => {
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

  const s3ConnectorIndexingStatuses: ConnectorIndexingStatus<
    S3Config,
    S3CredentialJson
  >[] = connectorIndexingStatuses.filter(
    (connectorIndexingStatus) =>
      connectorIndexingStatus.connector.source === "s3"
  );

  const s3Credential: Credential<S3CredentialJson> | undefined =
    credentialsData.find(
      (credential) => credential.credential_json?.aws_access_key_id
    );

  return (
    <>
      {popup}
      <Title className="mb-2 mt-6 ml-auto mr-auto">
        Step 1: Provide your access info
      </Title>
      {s3Credential ? (
        <>
          {" "}
          <div className="flex mb-1 text-sm">
            <p className="my-auto">Existing AWS Access Key ID: </p>
            <p className="ml-1 italic my-auto">
              {s3Credential.credential_json.aws_access_key_id}
            </p>
            <button
              className="ml-1 hover:bg-hover rounded p-1"
              onClick={async () => {
                if (s3ConnectorIndexingStatuses.length > 0) {
                  setPopup({
                    type: "error",
                    message:
                      "Must delete all connectors before deleting credentials",
                  });
                  return;
                }
                await adminDeleteCredential(s3Credential.id);
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
                If AWS Access Key ID and AWS Secret Access Key are provided,
                they will be used for authenticating the connector.
              </li>
              <li>Otherwise, the Profile Name will be used (if provided).</li>
              <li>
                If no credentials are provided, then the connector will try to
                authenticate with any default AWS credentials available.
              </li>
            </ul>
          </Text>
          <Card className="mt-4">
            <CredentialForm<S3CredentialJson>
              formBody={
                <>
                  <TextFormField
                    name="aws_access_key_id"
                    label="AWS Access Key ID:"
                  />
                  <TextFormField
                    name="aws_secret_access_key"
                    label="AWS Secret Access Key:"
                  />
                </>
              }
              validationSchema={Yup.object().shape({
                aws_access_key_id: Yup.string().default(""),
                aws_secret_access_key: Yup.string().default(""),
              })}
              initialValues={{
                aws_access_key_id: "",
                aws_secret_access_key: "",
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
        Step 2: Which S3 bucket do you want to make searchable?
      </Title>

      {s3ConnectorIndexingStatuses.length > 0 && (
        <>
          <Title className="mb-2 mt-6 ml-auto mr-auto">
            S3 indexing status
          </Title>
          <Text className="mb-2">
            The latest changes are fetched every 10 minutes.
          </Text>
          <div className="mb-2">
            <ConnectorsTable<S3Config, S3CredentialJson>
              includeName={true}
              connectorIndexingStatuses={s3ConnectorIndexingStatuses}
              liveCredential={s3Credential}
              getCredential={(credential) => {
                return <div></div>;
              }}
              onCredentialLink={async (connectorId) => {
                if (s3Credential) {
                  await linkCredential(connectorId, s3Credential.id);
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

      {s3Credential && (
        <>
          <Card className="mt-4">
            <h2 className="font-bold mb-3">Create Connection</h2>
            <Text className="mb-4">
              Press connect below to start the connection to your S3 bucket.
            </Text>
            <ConnectorForm<S3Config>
              nameBuilder={(values) => `S3Connector-${values.bucket_name}`}
              ccPairNameBuilder={(values) =>
                `S3Connector-${values.bucket_name}`
              }
              source="s3"
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
                  .oneOf(["s3"])
                  .required("Bucket type must be s3"),
                bucket_name: Yup.string().required(
                  "Please enter the name of the s3 bucket to index, e.g. my-test-bucket"
                ),
                prefix: Yup.string().default(""),
              })}
              initialValues={{
                bucket_type: "s3",
                bucket_name: "",
                prefix: "",
              }}
              refreshFreq={60 * 60 * 24} // 1 day
              credentialId={s3Credential.id}
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
      <AdminPageTitle icon={<S3Icon size={32} />} title="S3 Storage" />
      <S3Main key={1} />
    </div>
  );
}
