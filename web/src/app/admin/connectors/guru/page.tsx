"use client";

import * as Yup from "yup";
import { GuruIcon, TrashIcon } from "@/components/icons/icons";
import { TextFormField } from "@/components/admin/connectors/Field";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import { CredentialForm } from "@/components/admin/connectors/CredentialForm";
import {
  Credential,
  ConnectorIndexingStatus,
  GuruConfig,
  GuruCredentialJson,
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

  const guruConnectorIndexingStatuses: ConnectorIndexingStatus<
    GuruConfig,
    GuruCredentialJson
  >[] = connectorIndexingStatuses.filter(
    (connectorIndexingStatus) =>
      connectorIndexingStatus.connector.source === "guru"
  );
  const guruCredential: Credential<GuruCredentialJson> | undefined =
    credentialsData.find((credential) => credential.credential_json?.guru_user);

  return (
    <>
      {popup}
      <Text>
        This connector allows you to sync all your Guru Cards into Danswer.
      </Text>

      <Title className="mb-2 mt-6 ml-auto mr-auto">
        Step 1: Provide your Credentials
      </Title>

      {guruCredential ? (
        <>
          <div className="flex mb-1 text-sm">
            <Text className="my-auto">Existing Access Token: </Text>
            <Text className="ml-1 italic my-auto max-w-md truncate">
              {guruCredential.credential_json?.guru_user_token}
            </Text>
            <button
              className="ml-1 hover:bg-hover rounded p-1"
              onClick={async () => {
                if (guruConnectorIndexingStatuses.length > 0) {
                  setPopup({
                    type: "error",
                    message:
                      "Must delete all connectors before deleting credentials",
                  });
                  return;
                }
                await adminDeleteCredential(guruCredential.id);
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
            To use the Guru connector, first follow the guide{" "}
            <a
              className="text-link"
              href="https://help.getguru.com/s/article/how-to-obtain-your-api-credentials"
              target="_blank"
            >
              here
            </a>{" "}
            to generate a User Token.
          </Text>
          <Card className="mt-4">
            <CredentialForm<GuruCredentialJson>
              formBody={
                <>
                  <TextFormField name="guru_user" label="Username:" />
                  <TextFormField
                    name="guru_user_token"
                    label="User Token:"
                    type="password"
                  />
                </>
              }
              validationSchema={Yup.object().shape({
                guru_user: Yup.string().required(
                  "Please enter your Guru username"
                ),
                guru_user_token: Yup.string().required(
                  "Please enter your Guru access token"
                ),
              })}
              initialValues={{
                guru_user: "",
                guru_user_token: "",
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
        Step 2: Start indexing!
      </Title>
      {guruCredential ? (
        !guruConnectorIndexingStatuses.length ? (
          <>
            <Text className="mb-2">
              Click the button below to start indexing! We will pull the latest
              features, components, and products from Guru every <b>10</b>{" "}
              minutes.
            </Text>
            <div className="flex">
              <ConnectorForm<GuruConfig>
                nameBuilder={() => "GuruConnector"}
                ccPairNameBuilder={() => "Guru"}
                source="guru"
                inputType="poll"
                formBody={null}
                validationSchema={Yup.object().shape({})}
                initialValues={{}}
                refreshFreq={10 * 60} // 10 minutes
                credentialId={guruCredential.id}
              />
            </div>
          </>
        ) : (
          <>
            <Text className="mb-2">
              Guru connector is setup! We are pulling the latest cards from Guru
              every <b>10</b> minutes.
            </Text>
            <ConnectorsTable<GuruConfig, GuruCredentialJson>
              connectorIndexingStatuses={guruConnectorIndexingStatuses}
              liveCredential={guruCredential}
              getCredential={(credential) => {
                return (
                  <div>
                    <p>{credential.credential_json.guru_user}</p>
                  </div>
                );
              }}
              onCredentialLink={async (connectorId) => {
                if (guruCredential) {
                  await linkCredential(connectorId, guruCredential.id);
                  mutate("/api/manage/admin/connector/indexing-status");
                }
              }}
              onUpdate={() =>
                mutate("/api/manage/admin/connector/indexing-status")
              }
            />
          </>
        )
      ) : (
        <>
          <Text>
            Please provide your access token in Step 1 first! Once done with
            that, you can then start indexing all your Guru cards.
          </Text>
        </>
      )}
    </>
  );
};

export default function Page() {
  return (
    <div className="mx-auto container">
      <AdminPageTitle icon={<GuruIcon size={32} />} title="Guru" />

      <Main />
    </div>
  );
}
