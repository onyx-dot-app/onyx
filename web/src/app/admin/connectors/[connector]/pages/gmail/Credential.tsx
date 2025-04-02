import { Button } from "@/components/Button";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import React, { useState, useEffect } from "react";
import { useSWRConfig } from "swr";
import * as Yup from "yup";
import { useRouter } from "next/navigation";
import { adminDeleteCredential } from "@/lib/credential";
import { setupGmailOAuth } from "@/lib/gmail";
import { GMAIL_AUTH_IS_ADMIN_COOKIE_NAME } from "@/lib/constants";
import Cookies from "js-cookie";
import { TextFormField } from "@/components/admin/connectors/Field";
import { Form, Formik } from "formik";
import { User } from "@/lib/types";
import CardSection from "@/components/admin/CardSection";
import {
  Credential,
  GmailCredentialJson,
  GmailServiceAccountCredentialJson,
} from "@/lib/connectors/credentials";
import { refreshAllGoogleData } from "@/lib/googleConnector";
import { ValidSources } from "@/lib/types";
import { buildSimilarCredentialInfoURL } from "@/app/admin/connector/[ccPairId]/lib";

type GmailCredentialJsonTypes = "authorized_user" | "service_account";

const DriveJsonUpload = ({
  setPopup,
  onSuccess,
}: {
  setPopup: (popupSpec: PopupSpec | null) => void;
  onSuccess?: () => void;
}) => {
  const { mutate } = useSWRConfig();
  const [credentialJsonStr, setCredentialJsonStr] = useState<
    string | undefined
  >();

  return (
    <>
      <input
        className={
          "mr-3 text-sm text-text-900 border border-background-300 overflow-visible " +
          "cursor-pointer bg-background dark:text-text-400 focus:outline-none " +
          "dark:bg-background-700 dark:border-background-600 dark:placeholder-text-400"
        }
        type="file"
        accept=".json"
        onChange={(event) => {
          if (!event.target.files) {
            return;
          }
          const file = event.target.files[0];
          const reader = new FileReader();

          reader.onload = function (loadEvent) {
            if (!loadEvent?.target?.result) {
              return;
            }
            const fileContents = loadEvent.target.result;
            setCredentialJsonStr(fileContents as string);
          };

          reader.readAsText(file);
        }}
      />

      <Button
        disabled={!credentialJsonStr}
        onClick={async () => {
          // check if the JSON is a app credential or a service account credential
          let credentialFileType: GmailCredentialJsonTypes;
          try {
            const appCredentialJson = JSON.parse(credentialJsonStr!);
            if (appCredentialJson.web) {
              credentialFileType = "authorized_user";
            } else if (appCredentialJson.type === "service_account") {
              credentialFileType = "service_account";
            } else {
              throw new Error(
                "Unknown credential type, expected one of 'OAuth Web application' or 'Service Account'"
              );
            }
          } catch (e) {
            setPopup({
              message: `Invalid file provided - ${e}`,
              type: "error",
            });
            return;
          }

          if (credentialFileType === "authorized_user") {
            const response = await fetch(
              "/api/manage/admin/connector/gmail/app-credential",
              {
                method: "PUT",
                headers: {
                  "Content-Type": "application/json",
                },
                body: credentialJsonStr,
              }
            );
            if (response.ok) {
              setPopup({
                message: "Successfully uploaded app credentials",
                type: "success",
              });
              mutate("/api/manage/admin/connector/gmail/app-credential");
              if (onSuccess) {
                onSuccess();
              }
            } else {
              const errorMsg = await response.text();
              setPopup({
                message: `Failed to upload app credentials - ${errorMsg}`,
                type: "error",
              });
            }
          }

          if (credentialFileType === "service_account") {
            const response = await fetch(
              "/api/manage/admin/connector/gmail/service-account-key",
              {
                method: "PUT",
                headers: {
                  "Content-Type": "application/json",
                },
                body: credentialJsonStr,
              }
            );
            if (response.ok) {
              setPopup({
                message: "Successfully uploaded service account key",
                type: "success",
              });
              mutate("/api/manage/admin/connector/gmail/service-account-key");
              if (onSuccess) {
                onSuccess();
              }
            } else {
              const errorMsg = await response.text();
              setPopup({
                message: `Failed to upload service account key - ${errorMsg}`,
                type: "error",
              });
            }
          }
        }}
      >
        Upload
      </Button>
    </>
  );
};

interface DriveJsonUploadSectionProps {
  setPopup: (popupSpec: PopupSpec | null) => void;
  appCredentialData?: { client_id: string };
  serviceAccountCredentialData?: { service_account_email: string };
  isAdmin: boolean;
  onSuccess?: () => void;
}

export const GmailJsonUploadSection = ({
  setPopup,
  appCredentialData,
  serviceAccountCredentialData,
  isAdmin,
  onSuccess,
}: DriveJsonUploadSectionProps) => {
  const { mutate } = useSWRConfig();
  const router = useRouter();
  const [localServiceAccountData, setLocalServiceAccountData] = useState(
    serviceAccountCredentialData
  );
  const [localAppCredentialData, setLocalAppCredentialData] =
    useState(appCredentialData);

  // Update local state when props change
  useEffect(() => {
    setLocalServiceAccountData(serviceAccountCredentialData);
    setLocalAppCredentialData(appCredentialData);
  }, [serviceAccountCredentialData, appCredentialData]);

  const handleSuccess = () => {
    if (onSuccess) {
      onSuccess();
    } else {
      refreshAllGoogleData(ValidSources.Gmail);
    }
  };

  if (localServiceAccountData?.service_account_email) {
    return (
      <div className="mt-2 text-sm">
        <div>
          Found existing service account key with the following <b>Email:</b>
          <p className="italic mt-1">
            {localServiceAccountData.service_account_email}
          </p>
        </div>
        {isAdmin ? (
          <>
            <div className="mt-4 mb-1">
              If you want to update these credentials, delete the existing
              credentials through the button below, and then upload a new
              credentials JSON.
            </div>
            <Button
              onClick={async () => {
                const response = await fetch(
                  "/api/manage/admin/connector/gmail/service-account-key",
                  {
                    method: "DELETE",
                  }
                );
                if (response.ok) {
                  mutate(
                    "/api/manage/admin/connector/gmail/service-account-key"
                  );
                  // Also mutate the credential endpoints to ensure Step 2 is reset
                  mutate(buildSimilarCredentialInfoURL(ValidSources.Gmail));
                  setPopup({
                    message: "Successfully deleted service account key",
                    type: "success",
                  });
                  // Immediately update local state
                  setLocalServiceAccountData(undefined);
                  handleSuccess();
                } else {
                  const errorMsg = await response.text();
                  setPopup({
                    message: `Failed to delete service account key - ${errorMsg}`,
                    type: "error",
                  });
                }
              }}
            >
              Delete
            </Button>
          </>
        ) : (
          <>
            <div className="mt-4 mb-1">
              To change these credentials, please contact an administrator.
            </div>
          </>
        )}
      </div>
    );
  }

  if (localAppCredentialData?.client_id) {
    return (
      <div className="mt-2 text-sm">
        <div>
          Found existing app credentials with the following <b>Client ID:</b>
          <p className="italic mt-1">{localAppCredentialData.client_id}</p>
        </div>
        {isAdmin ? (
          <>
            <div className="mt-4 mb-1">
              If you want to update these credentials, delete the existing
              credentials through the button below, and then upload a new
              credentials JSON.
            </div>
            <Button
              onClick={async () => {
                const response = await fetch(
                  "/api/manage/admin/connector/gmail/app-credential",
                  {
                    method: "DELETE",
                  }
                );
                if (response.ok) {
                  mutate("/api/manage/admin/connector/gmail/app-credential");
                  // Also mutate the credential endpoints to ensure Step 2 is reset
                  mutate(buildSimilarCredentialInfoURL(ValidSources.Gmail));
                  setPopup({
                    message: "Successfully deleted app credentials",
                    type: "success",
                  });
                  // Immediately update local state
                  setLocalAppCredentialData(undefined);
                  handleSuccess();
                } else {
                  const errorMsg = await response.text();
                  setPopup({
                    message: `Failed to delete app credential - ${errorMsg}`,
                    type: "error",
                  });
                }
              }}
            >
              Delete
            </Button>
          </>
        ) : (
          <div className="mt-4 mb-1">
            To change these credentials, please contact an administrator.
          </div>
        )}
      </div>
    );
  }

  if (!isAdmin) {
    return (
      <div className="mt-2">
        <p className="text-sm mb-2">
          Curators are unable to set up the Gmail credentials. To add a Gmail
          connector, please contact an administrator.
        </p>
      </div>
    );
  }

  return (
    <div className="mt-2">
      <p className="text-sm mb-2">
        Follow the guide{" "}
        <a
          className="text-link"
          target="_blank"
          href="https://docs.onyx.app/connectors/gmail#authorization"
          rel="noreferrer"
        >
          here
        </a>{" "}
        to either (1) setup a Google OAuth App in your company workspace or (2)
        create a Service Account.
        <br />
        <br />
        Download the credentials JSON if choosing option (1) or the Service
        Account key JSON if choosing option (2), and upload it here.
      </p>
      <DriveJsonUpload setPopup={setPopup} onSuccess={handleSuccess} />
    </div>
  );
};

interface DriveCredentialSectionProps {
  gmailPublicCredential?: Credential<GmailCredentialJson>;
  gmailServiceAccountCredential?: Credential<GmailServiceAccountCredentialJson>;
  serviceAccountKeyData?: { service_account_email: string };
  appCredentialData?: { client_id: string };
  setPopup: (popupSpec: PopupSpec | null) => void;
  refreshCredentials: () => void;
  connectorExists: boolean;
  user: User | null;
}

async function handleRevokeAccess(
  connectorExists: boolean,
  setPopup: (popupSpec: PopupSpec | null) => void,
  existingCredential:
    | Credential<GmailCredentialJson>
    | Credential<GmailServiceAccountCredentialJson>,
  refreshCredentials: () => void
) {
  if (connectorExists) {
    const message =
      "Cannot revoke the Gmail credential while any connector is still associated with the credential. " +
      "Please delete all associated connectors, then try again.";
    setPopup({
      message: message,
      type: "error",
    });
    return;
  }

  await adminDeleteCredential(existingCredential.id);
  setPopup({
    message: "Successfully revoked the Gmail credential!",
    type: "success",
  });

  refreshCredentials();
}

export const GmailAuthSection = ({
  gmailPublicCredential,
  gmailServiceAccountCredential,
  serviceAccountKeyData,
  appCredentialData,
  setPopup,
  refreshCredentials,
  connectorExists,
  user,
}: DriveCredentialSectionProps) => {
  const router = useRouter();
  const [isAuthenticating, setIsAuthenticating] = useState(false);
  const [localServiceAccountData, setLocalServiceAccountData] = useState(
    serviceAccountKeyData
  );
  const [localAppCredentialData, setLocalAppCredentialData] =
    useState(appCredentialData);
  const [localGmailPublicCredential, setLocalGmailPublicCredential] = useState(
    gmailPublicCredential
  );
  const [
    localGmailServiceAccountCredential,
    setLocalGmailServiceAccountCredential,
  ] = useState(gmailServiceAccountCredential);

  // Update local state when props change
  useEffect(() => {
    setLocalServiceAccountData(serviceAccountKeyData);
    setLocalAppCredentialData(appCredentialData);
    setLocalGmailPublicCredential(gmailPublicCredential);
    setLocalGmailServiceAccountCredential(gmailServiceAccountCredential);
  }, [
    serviceAccountKeyData,
    appCredentialData,
    gmailPublicCredential,
    gmailServiceAccountCredential,
  ]);

  const existingCredential =
    localGmailPublicCredential || localGmailServiceAccountCredential;
  if (existingCredential) {
    return (
      <>
        <p className="mb-2 text-sm">
          <i>Uploaded and authenticated credential already exists!</i>
        </p>
        <Button
          onClick={async () => {
            handleRevokeAccess(
              connectorExists,
              setPopup,
              existingCredential,
              refreshCredentials
            );
          }}
        >
          Revoke Access
        </Button>
      </>
    );
  }

  if (localServiceAccountData?.service_account_email) {
    return (
      <div>
        <Formik
          initialValues={{
            google_primary_admin: user?.email || "",
          }}
          validationSchema={Yup.object().shape({
            google_primary_admin: Yup.string()
              .email("Must be a valid email")
              .required("Required"),
          })}
          onSubmit={async (values, formikHelpers) => {
            formikHelpers.setSubmitting(true);
            try {
              const response = await fetch(
                "/api/manage/admin/connector/gmail/service-account-credential",
                {
                  method: "PUT",
                  headers: {
                    "Content-Type": "application/json",
                  },
                  body: JSON.stringify({
                    google_primary_admin: values.google_primary_admin,
                  }),
                }
              );

              if (response.ok) {
                setPopup({
                  message: "Successfully created service account credential",
                  type: "success",
                });
                refreshCredentials();
              } else {
                const errorMsg = await response.text();
                setPopup({
                  message: `Failed to create service account credential - ${errorMsg}`,
                  type: "error",
                });
              }
            } catch (error) {
              setPopup({
                message: `Failed to create service account credential - ${error}`,
                type: "error",
              });
            } finally {
              formikHelpers.setSubmitting(false);
            }
          }}
        >
          {({ isSubmitting }) => (
            <Form>
              <TextFormField
                name="google_primary_admin"
                label="Primary Admin Email:"
                subtext="Enter the email of an admin/owner of the Google Organization that owns the Gmail account(s) you want to index."
              />
              <div className="flex">
                <Button type="submit" disabled={isSubmitting}>
                  Create Credential
                </Button>
              </div>
            </Form>
          )}
        </Formik>
      </div>
    );
  }

  if (localAppCredentialData?.client_id) {
    return (
      <div className="text-sm mb-4">
        <p className="mb-2">
          Next, you must provide credentials via OAuth. This gives us read
          access to the emails you have access to in your Gmail account.
        </p>
        <Button
          onClick={async () => {
            setIsAuthenticating(true);
            try {
              Cookies.set(GMAIL_AUTH_IS_ADMIN_COOKIE_NAME, "true", {
                path: "/",
              });
              const [authUrl, errorMsg] = await setupGmailOAuth({
                isAdmin: true,
              });

              if (authUrl) {
                router.push(authUrl);
              } else {
                setPopup({
                  message: errorMsg,
                  type: "error",
                });
                setIsAuthenticating(false);
              }
            } catch (error) {
              setPopup({
                message: `Failed to authenticate with Gmail - ${error}`,
                type: "error",
              });
              setIsAuthenticating(false);
            }
          }}
          disabled={isAuthenticating}
        >
          {isAuthenticating ? "Authenticating..." : "Authenticate with Gmail"}
        </Button>
      </div>
    );
  }

  // case where no keys have been uploaded in step 1
  return (
    <p className="text-sm">
      Please upload either a OAuth Client Credential JSON or a Gmail Service
      Account Key JSON in Step 1 before moving onto Step 2.
    </p>
  );
};
