import { Button } from "@/components/ui/button";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import React, { useState, useEffect } from "react";
import { useSWRConfig } from "swr";
import * as Yup from "yup";
import { useRouter } from "next/navigation";
import { adminDeleteCredential } from "@/lib/credential";
import { setupGmailOAuth } from "@/lib/gmail";
import { GMAIL_AUTH_IS_ADMIN_COOKIE_NAME } from "@/lib/constants";
import Cookies from "js-cookie";
import {
  TextFormField,
  SectionHeader,
  SubLabel,
} from "@/components/admin/connectors/Field";
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
import {
  FiFile,
  FiUpload,
  FiTrash2,
  FiCheck,
  FiLink,
  FiAlertTriangle,
} from "react-icons/fi";
import { cn, truncateString } from "@/lib/utils";

type GmailCredentialJsonTypes = "authorized_user" | "service_account";

const GmailCredentialUpload = ({
  setPopup,
  onSuccess,
}: {
  setPopup: (popupSpec: PopupSpec | null) => void;
  onSuccess?: () => void;
}) => {
  const { mutate } = useSWRConfig();
  const [isUploading, setIsUploading] = useState(false);
  const [fileName, setFileName] = useState<string | undefined>();
  const [isDragging, setIsDragging] = useState(false);

  const handleFileUpload = async (file: File) => {
    setIsUploading(true);
    setFileName(file.name);

    const reader = new FileReader();
    reader.onload = async (loadEvent) => {
      if (!loadEvent?.target?.result) {
        setIsUploading(false);
        return;
      }

      const credentialJsonStr = loadEvent.target.result as string;

      // Check credential type
      let credentialFileType: GmailCredentialJsonTypes;
      try {
        const appCredentialJson = JSON.parse(credentialJsonStr);
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
        setIsUploading(false);
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
      setIsUploading(false);
    };

    reader.readAsText(file);
  };

  const handleDragEnter = (e: React.DragEvent<HTMLLabelElement>) => {
    e.preventDefault();
    e.stopPropagation();
    if (!isUploading) {
      setIsDragging(true);
    }
  };

  const handleDragLeave = (e: React.DragEvent<HTMLLabelElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };

  const handleDragOver = (e: React.DragEvent<HTMLLabelElement>) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const handleDrop = (e: React.DragEvent<HTMLLabelElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);

    if (isUploading) return;

    const files = e.dataTransfer.files;
    if (files.length > 0) {
      const file = files[0];
      if (file.type === "application/json" || file.name.endsWith(".json")) {
        handleFileUpload(file);
      } else {
        setPopup({
          message: "Please upload a JSON file",
          type: "error",
        });
      }
    }
  };

  return (
    <div className="flex flex-col mt-4">
      <div className="flex items-center">
        <div className="relative flex flex-1 items-center">
          <label
            className={cn(
              "flex h-10 items-center justify-center w-full px-4 py-2 border border-dashed rounded-md transition-colors",
              isUploading
                ? "opacity-70 cursor-not-allowed border-background-400 bg-background-50/30"
                : isDragging
                  ? "bg-background-50/50 border-primary dark:border-primary"
                  : "cursor-pointer hover:bg-background-50/30 hover:border-primary dark:hover:border-primary border-background-300 dark:border-background-600"
            )}
            onDragEnter={handleDragEnter}
            onDragLeave={handleDragLeave}
            onDragOver={handleDragOver}
            onDrop={handleDrop}
          >
            <div className="flex items-center space-x-2">
              {isUploading ? (
                <div className="h-4 w-4 border-t-2 border-b-2 border-primary rounded-full animate-spin"></div>
              ) : (
                <FiFile className="h-4 w-4 text-text-500" />
              )}
              <span className="text-sm text-text-500">
                {isUploading
                  ? `Uploading ${truncateString(fileName || "file", 50)}...`
                  : isDragging
                    ? "Drop JSON file here"
                    : truncateString(
                        fileName || "Select or drag JSON credentials file...",
                        50
                      )}
              </span>
            </div>
            <input
              className="sr-only"
              type="file"
              accept=".json"
              disabled={isUploading}
              onChange={(event) => {
                if (!event.target.files?.length) {
                  return;
                }
                const file = event.target.files[0];
                handleFileUpload(file);
              }}
            />
          </label>
        </div>
      </div>
    </div>
  );
};

interface GmailJsonUploadSectionProps {
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
}: GmailJsonUploadSectionProps) => {
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

  if (!isAdmin) {
    return (
      <div>
        <div className="flex items-start py-3 px-4 bg-yellow-50/30 dark:bg-yellow-900/5 rounded">
          <FiAlertTriangle className="text-yellow-500 h-5 w-5 mr-2 mt-0.5 flex-shrink-0" />
          <p className="text-sm">
            Curators are unable to set up the Gmail credentials. To add a Gmail
            connector, please contact an administrator.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div>
      <p className="text-sm mb-3">
        To connect your Gmail, create credentials (either OAuth App or Service
        Account), download the JSON file, and upload it below.
      </p>
      <div className="mb-4">
        <a
          className="text-primary hover:text-primary/80 flex items-center gap-1 text-sm"
          target="_blank"
          href="https://docs.onyx.app/connectors/gmail#authorization"
          rel="noreferrer"
        >
          <FiLink className="h-3 w-3" />
          View detailed setup instructions
        </a>
      </div>

      {(localServiceAccountData?.service_account_email ||
        localAppCredentialData?.client_id) && (
        <div className="mb-4">
          <div className="relative flex flex-1 items-center">
            <label
              className={cn(
                "flex h-10 items-center justify-center w-full px-4 py-2 border border-dashed rounded-md transition-colors",
                false
                  ? "opacity-70 cursor-not-allowed border-background-400 bg-background-50/30"
                  : "cursor-pointer hover:bg-background-50/30 hover:border-primary dark:hover:border-primary border-background-300 dark:border-background-600"
              )}
            >
              <div className="flex items-center space-x-2">
                {false ? (
                  <div className="h-4 w-4 border-t-2 border-b-2 border-primary rounded-full animate-spin"></div>
                ) : (
                  <FiFile className="h-4 w-4 text-text-500" />
                )}
                <span className="text-sm text-text-500">
                  {truncateString(
                    localServiceAccountData?.service_account_email ||
                      localAppCredentialData?.client_id ||
                      "",
                    50
                  )}
                </span>
              </div>
            </label>
          </div>
          {isAdmin && (
            <div className="mt-2">
              <Button
                variant="destructive"
                type="button"
                onClick={async () => {
                  const endpoint =
                    localServiceAccountData?.service_account_email
                      ? "/api/manage/admin/connector/gmail/service-account-key"
                      : "/api/manage/admin/connector/gmail/app-credential";

                  const response = await fetch(endpoint, {
                    method: "DELETE",
                  });

                  if (response.ok) {
                    mutate(endpoint);
                    // Also mutate the credential endpoints to ensure Step 2 is reset
                    mutate(buildSimilarCredentialInfoURL(ValidSources.Gmail));
                    setPopup({
                      message: `Successfully deleted ${
                        localServiceAccountData
                          ? "service account key"
                          : "app credentials"
                      }`,
                      type: "success",
                    });
                    // Immediately update local state
                    if (localServiceAccountData) {
                      setLocalServiceAccountData(undefined);
                    } else {
                      setLocalAppCredentialData(undefined);
                    }
                    handleSuccess();
                  } else {
                    const errorMsg = await response.text();
                    setPopup({
                      message: `Failed to delete credentials - ${errorMsg}`,
                      type: "error",
                    });
                  }
                }}
              >
                Delete Credentials
              </Button>
            </div>
          )}
        </div>
      )}

      {!(
        localServiceAccountData?.service_account_email ||
        localAppCredentialData?.client_id
      ) && (
        <GmailCredentialUpload setPopup={setPopup} onSuccess={handleSuccess} />
      )}
    </div>
  );
};

interface GmailCredentialSectionProps {
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
}: GmailCredentialSectionProps) => {
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
      <div>
        <div className="mt-4">
          <div className="py-3 px-4 bg-blue-50/30 dark:bg-blue-900/5 rounded mb-4 flex items-start">
            <FiCheck className="text-blue-500 h-5 w-5 mr-2 mt-0.5 flex-shrink-0" />
            <div className="flex-1">
              <span className="font-medium block">Authentication Complete</span>
              <p className="text-sm mt-1 text-text-500 dark:text-text-400 break-words">
                Your Gmail credentials have been successfully uploaded and
                authenticated.
              </p>
            </div>
          </div>
          <Button
            variant="destructive"
            type="button"
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
        </div>
      </div>
    );
  }

  // If no credentials are uploaded, show message to complete step 1 first
  if (
    !localServiceAccountData?.service_account_email &&
    !localAppCredentialData?.client_id
  ) {
    return (
      <div>
        <SectionHeader>Gmail Authentication</SectionHeader>
        <div className="mt-4">
          <div className="flex items-start py-3 px-4 bg-yellow-50/30 dark:bg-yellow-900/5 rounded">
            <FiAlertTriangle className="text-yellow-500 h-5 w-5 mr-2 mt-0.5 flex-shrink-0" />
            <p className="text-sm">
              Please complete Step 1 by uploading either OAuth credentials or a
              Service Account key before proceeding with authentication.
            </p>
          </div>
        </div>
      </div>
    );
  }

  if (localServiceAccountData?.service_account_email) {
    return (
      <div>
        <div className="mt-4">
          <div className="py-3 px-4 bg-background-50/30 dark:bg-background-900/20 rounded mb-4">
            <p className="text-sm">
              Enter the email of an admin/owner of the Google Organization that
              owns the Gmail account(s) you want to index.
            </p>
          </div>

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
              <Form className="space-y-4">
                <TextFormField
                  name="google_primary_admin"
                  label="Primary Admin Email:"
                  subtext="Enter the email of an admin/owner of the Google Organization that owns the Gmail account(s) you want to index."
                />
                <div className="flex">
                  <Button type="submit" disabled={isSubmitting}>
                    {isSubmitting ? "Creating..." : "Create Credential"}
                  </Button>
                </div>
              </Form>
            )}
          </Formik>
        </div>
      </div>
    );
  }

  if (localAppCredentialData?.client_id) {
    return (
      <div>
        <div className="bg-background-50/30 dark:bg-background-900/20 rounded mb-4">
          <p className="text-sm">
            Next, you need to authenticate with Gmail via OAuth. This gives us
            read access to the emails you have access to in your Gmail account.
          </p>
        </div>
        <Button
          disabled={isAuthenticating}
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
        >
          {isAuthenticating ? "Authenticating..." : "Authenticate with Gmail"}
        </Button>
      </div>
    );
  }

  // This code path should not be reached with the new conditions above
  return null;
};
