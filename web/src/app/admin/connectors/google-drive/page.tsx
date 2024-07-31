"use client";

import * as Yup from "yup";
import { GoogleDriveIcon } from "@/components/icons/icons";
import useSWR, { useSWRConfig } from "swr";
import { FetchError, errorHandlingFetcher } from "@/lib/fetcher";
import { ErrorCallout } from "@/components/ErrorCallout";
import { LoadingAnimation } from "@/components/Loading";
import { PopupSpec, usePopup } from "@/components/admin/connectors/Popup";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import {
  ConnectorIndexingStatus,
  Credential,
  GoogleDriveConfig,
  GoogleDriveCredentialJson,
  GoogleDriveServiceAccountCredentialJson,
} from "@/lib/types";
import { linkCredential } from "@/lib/credential";
import { ConnectorForm } from "@/components/admin/connectors/ConnectorForm";
import {
  BooleanFormField,
  TextArrayFieldBuilder,
} from "@/components/admin/connectors/Field";
import { GoogleDriveConnectorsTable } from "./GoogleDriveConnectorsTable";
import { googleDriveConnectorNameBuilder } from "./utils";
import { DriveOAuthSection, DriveJsonUploadSection } from "./Credential";
import { usePublicCredentials } from "@/lib/hooks";
import { AdminPageTitle } from "@/components/admin/Title";
import { Card, Divider, Text, Title } from "@tremor/react";

interface GoogleDriveConnectorManagementProps {
  googleDrivePublicCredential?: Credential<GoogleDriveCredentialJson>;
  googleDriveServiceAccountCredential?: Credential<GoogleDriveServiceAccountCredentialJson>;
  googleDriveConnectorIndexingStatus: ConnectorIndexingStatus<
    GoogleDriveConfig,
    GoogleDriveCredentialJson
  > | null;
  googleDriveConnectorIndexingStatuses: ConnectorIndexingStatus<
    GoogleDriveConfig,
    GoogleDriveCredentialJson
  >[];
  credentialIsLinked: boolean;
  setPopup: (popupSpec: PopupSpec | null) => void;
}

const GoogleDriveConnectorManagement = ({
  googleDrivePublicCredential,
  googleDriveServiceAccountCredential,
  googleDriveConnectorIndexingStatus,
  googleDriveConnectorIndexingStatuses,
  credentialIsLinked,
  setPopup,
}: GoogleDriveConnectorManagementProps) => {
  const { mutate } = useSWRConfig();

  const liveCredential =
    googleDrivePublicCredential || googleDriveServiceAccountCredential;
  if (!liveCredential) {
    return (
      <Text>
        Please authenticate with Google Drive as described in Step 2! Once done
        with that, you can then move on to enable this connector.
      </Text>
    );
  }

  // NOTE: if the connector has no credential linked, then it will not be
  // returned by the indexing-status API
  // if (!googleDriveConnectorIndexingStatus) {
  //   return (
  //     <>
  //       <p className="text-sm mb-2">
  //         Fill out the form below to create a connector. We will refresh the
  //         latest documents from Google Drive every <b>10</b> minutes.
  //       </p>
  //       <div className="border-solid border-gray-600 border rounded-md p-6 mt-4">
  //         <h2 className="font-bold mb-3">Add Connector</h2>
  //         <ConnectorForm<GoogleDriveConfig>
  //           nameBuilder={googleDriveConnectorNameBuilder}
  //           source="google_drive"
  //           inputType="poll"
  //           formBodyBuilder={(values) => (
  //             <div>
  //               {TextArrayFieldBuilder({
  //                 name: "folder_paths",
  //                 label: "Folder Paths",
  //                 subtext:
  //                   "Specify 0 or more folder paths to index! For example, specifying the path " +
  //                   "'Engineering/Materials' will cause us to only index all files contained " +
  //                   "within the 'Materials' folder within the 'Engineering' folder. " +
  //                   "If no folder paths are specified, we will index all documents in your drive.",
  //               })(values)}
  //               <BooleanFormField
  //                 name="include_shared"
  //                 label="Include Shared"
  //               />
  //             </div>
  //           )}
  //           validationSchema={Yup.object().shape({
  //             folder_paths: Yup.array()
  //               .of(
  //                 Yup.string().required(
  //                   "Please specify a folder path for your google drive e.g. 'Engineering/Materials'"
  //                 )
  //               )
  //               .required(),
  //             include_shared: Yup.boolean().required(),
  //           })}
  //           initialValues={{
  //             folder_paths: [],
  //           }}
  //           refreshFreq={10 * 60} // 10 minutes
  //           onSubmit={async (isSuccess, responseJson) => {
  //             if (isSuccess && responseJson) {
  //               await linkCredential(
  //                 responseJson.id,
  //                 googleDrivePublicCredential.id
  //               );
  //               mutate("/api/manage/admin/connector/indexing-status");
  //             }
  //           }}
  //         />
  //       </div>
  //     </>
  //   );
  // }

  // If the connector has no credential, we will just hit the ^ section.
  // Leaving this in for now in case we want to change this behavior later
  // if (!credentialIsLinked) {
  //   <>
  //     <p className="text-sm mb-2">
  //       Click the button below to link your credentials! Once this is done, all
  //       public documents in your Google Drive will be searchable. We will
  //       refresh the latest documents every <b>10</b> minutes.
  //     </p>
  //     <Button
  //       onClick={async () => {
  //         await linkCredential(
  //           googleDriveConnectorIndexingStatus.connector.id,
  //           googleDrivePublicCredential.id
  //         );
  //         setPopup({
  //           message: "Successfully linked credentials!",
  //           type: "success",
  //         });
  //         mutate("/api/manage/admin/connector/indexing-status");
  //       }}
  //     >
  //       Link Credentials
  //     </Button>
  //   </>;
  // }

  return (
    <div>
      <Text>
        <div className="my-3">
          {googleDriveConnectorIndexingStatuses.length > 0 ? (
            <>
              Checkout the{" "}
              <a href="/admin/indexing/status" className="text-blue-500">
                status page
              </a>{" "}
              for the latest indexing status. We fetch the latest documents from
              Google Drive every <b>10</b> minutes.
            </>
          ) : (
            <p className="text-sm mb-2">
              Fill out the form below to create a connector. We will refresh the
              latest documents from Google Drive every <b>10</b> minutes.
            </p>
          )}
        </div>
      </Text>
      {googleDriveConnectorIndexingStatuses.length > 0 && (
        <>
          <div className="text-sm mb-2 font-bold">Existing Connectors:</div>
          <GoogleDriveConnectorsTable
            googleDriveConnectorIndexingStatuses={
              googleDriveConnectorIndexingStatuses
            }
            setPopup={setPopup}
          />
          <Divider />
        </>
      )}

      {googleDriveConnectorIndexingStatuses.length > 0 && (
        <h2 className="font-bold mt-3 text-sm">Add New Connector:</h2>
      )}
      <Card className="mt-4">
        <ConnectorForm<GoogleDriveConfig>
          nameBuilder={googleDriveConnectorNameBuilder}
          source="google_drive"
          inputType="poll"
          formBodyBuilder={(values) => (
            <>
              {TextArrayFieldBuilder({
                name: "folder_paths",
                label: "Folder Paths",
                subtext:
                  "Specify 0 or more folder paths to index! For example, specifying the path " +
                  "'Engineering/Materials' will cause us to only index all files contained " +
                  "within the 'Materials' folder within the 'Engineering' folder. " +
                  "If no folder paths are specified, we will index all documents in your drive.",
              })(values)}
              <BooleanFormField
                name="include_shared"
                label="Include Shared Files + Shared Drives"
                subtext={
                  "If checked, then we will also index all documents + drives shared with you. " +
                  "If this is combined with folder paths, then we will only index documents " +
                  "that match both criteria."
                }
              />
              <BooleanFormField
                name="follow_shortcuts"
                label="Follow Shortcuts"
                subtext={
                  "If checked, then will follow shortcuts to files and folder and " +
                  "attempt to index those as well."
                }
              />
              <BooleanFormField
                name="only_org_public"
                label="Only Org-Wide Public Docs"
                subtext={
                  "If checked, then only documents that are shared to the entire organization " +
                  "are included. Note: if you have multiple orgs, this check will pass for docs " +
                  "shared with any of the orgs."
                }
              />
            </>
          )}
          validationSchema={Yup.object().shape({
            folder_paths: Yup.array()
              .of(
                Yup.string().required(
                  "Please specify a folder path for your google drive e.g. 'Engineering/Materials'"
                )
              )
              .required(),
            include_shared: Yup.boolean().required(),
            follow_shortcuts: Yup.boolean().required(),
            only_org_public: Yup.boolean().required(),
          })}
          initialValues={{
            folder_paths: [],
            include_shared: false,
            follow_shortcuts: false,
            only_org_public: false,
          }}
          refreshFreq={10 * 60} // 10 minutes
          credentialId={liveCredential.id}
        />
      </Card>
    </div>
  );
};

const Main = () => {
  const {
    data: appCredentialData,
    isLoading: isAppCredentialLoading,
    error: isAppCredentialError,
  } = useSWR<{ client_id: string }, FetchError>(
    "/api/manage/admin/connector/google-drive/app-credential",
    errorHandlingFetcher
  );
  const {
    data: serviceAccountKeyData,
    isLoading: isServiceAccountKeyLoading,
    error: isServiceAccountKeyError,
  } = useSWR<{ service_account_email: string }, FetchError>(
    "/api/manage/admin/connector/google-drive/service-account-key",
    errorHandlingFetcher
  );
  const {
    data: connectorIndexingStatuses,
    isLoading: isConnectorIndexingStatusesLoading,
    error: connectorIndexingStatusesError,
  } = useSWR<ConnectorIndexingStatus<any, any>[], FetchError>(
    "/api/manage/admin/connector/indexing-status",
    errorHandlingFetcher
  );
  const {
    data: credentialsData,
    isLoading: isCredentialsLoading,
    error: credentialsError,
    refreshCredentials,
  } = usePublicCredentials();

  const { popup, setPopup } = usePopup();

  const appCredentialSuccessfullyFetched =
    appCredentialData ||
    (isAppCredentialError && isAppCredentialError.status === 404);
  const serviceAccountKeySuccessfullyFetched =
    serviceAccountKeyData ||
    (isServiceAccountKeyError && isServiceAccountKeyError.status === 404);

  if (
    (!appCredentialSuccessfullyFetched && isAppCredentialLoading) ||
    (!serviceAccountKeySuccessfullyFetched && isServiceAccountKeyLoading) ||
    (!connectorIndexingStatuses && isConnectorIndexingStatusesLoading) ||
    (!credentialsData && isCredentialsLoading)
  ) {
    return (
      <div className="mx-auto">
        <LoadingAnimation text="" />
      </div>
    );
  }

  if (credentialsError || !credentialsData) {
    return <ErrorCallout errorTitle="Failed to load credentials." />;
  }

  if (connectorIndexingStatusesError || !connectorIndexingStatuses) {
    return <ErrorCallout errorTitle="Failed to load connectors." />;
  }

  if (
    !appCredentialSuccessfullyFetched ||
    !serviceAccountKeySuccessfullyFetched
  ) {
    return (
      <ErrorCallout errorTitle="Error loading Google Drive app credentials. Contact an administrator." />
    );
  }

  const googleDrivePublicCredential:
    | Credential<GoogleDriveCredentialJson>
    | undefined = credentialsData.find(
    (credential) =>
      credential.credential_json?.google_drive_tokens && credential.admin_public
  );
  const googleDriveServiceAccountCredential:
    | Credential<GoogleDriveServiceAccountCredentialJson>
    | undefined = credentialsData.find(
    (credential) => credential.credential_json?.google_drive_service_account_key
  );
  const googleDriveConnectorIndexingStatuses: ConnectorIndexingStatus<
    GoogleDriveConfig,
    GoogleDriveCredentialJson
  >[] = connectorIndexingStatuses.filter(
    (connectorIndexingStatus) =>
      connectorIndexingStatus.connector.source === "google_drive"
  );
  const googleDriveConnectorIndexingStatus =
    googleDriveConnectorIndexingStatuses[0];

  const credentialIsLinked =
    (googleDriveConnectorIndexingStatus !== undefined &&
      googleDrivePublicCredential !== undefined &&
      googleDriveConnectorIndexingStatus.connector.credential_ids.includes(
        googleDrivePublicCredential.id
      )) ||
    (googleDriveConnectorIndexingStatus !== undefined &&
      googleDriveServiceAccountCredential !== undefined &&
      googleDriveConnectorIndexingStatus.connector.credential_ids.includes(
        googleDriveServiceAccountCredential.id
      ));

  return (
    <>
      {popup}
      <Title className="mb-2 mt-6 ml-auto mr-auto">
        Step 1: Provide your Credentials
      </Title>
      <DriveJsonUploadSection
        setPopup={setPopup}
        appCredentialData={appCredentialData}
        serviceAccountCredentialData={serviceAccountKeyData}
      />

      <Title className="mb-2 mt-6 ml-auto mr-auto">
        Step 2: Authenticate with Danswer
      </Title>
      <DriveOAuthSection
        setPopup={setPopup}
        refreshCredentials={refreshCredentials}
        googleDrivePublicCredential={googleDrivePublicCredential}
        googleDriveServiceAccountCredential={
          googleDriveServiceAccountCredential
        }
        appCredentialData={appCredentialData}
        serviceAccountKeyData={serviceAccountKeyData}
        connectorExists={googleDriveConnectorIndexingStatuses.length > 0}
      />

      <Title className="mb-2 mt-6 ml-auto mr-auto">
        Step 3: Start Indexing!
      </Title>
      <GoogleDriveConnectorManagement
        googleDrivePublicCredential={googleDrivePublicCredential}
        googleDriveServiceAccountCredential={
          googleDriveServiceAccountCredential
        }
        googleDriveConnectorIndexingStatus={googleDriveConnectorIndexingStatus}
        googleDriveConnectorIndexingStatuses={
          googleDriveConnectorIndexingStatuses
        }
        credentialIsLinked={credentialIsLinked}
        setPopup={setPopup}
      />
    </>
  );
};

export default function Page() {
  return (
    <div className="mx-auto container">
      <AdminPageTitle
        icon={<GoogleDriveIcon size={32} />}
        title="Google Drive"
      />

      <Main />
    </div>
  );
}
