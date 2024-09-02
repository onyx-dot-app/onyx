import { PopupSpec } from "@/components/admin/connectors/Popup";
import { useState } from "react";
import { useSWRConfig } from "swr";
import * as Yup from "yup";
import { useRouter } from "next/navigation";
import {
  Credential,
  GoogleDriveCredentialJson,
  GoogleDriveServiceAccountCredentialJson,
} from "@/lib/types";
import { adminDeleteCredential } from "@/lib/credential";
import { setupGoogleDriveOAuth } from "@/lib/googleDrive";
import { GOOGLE_DRIVE_AUTH_IS_ADMIN_COOKIE_NAME } from "@/lib/constants";
import Cookies from "js-cookie";
import { TextFormField } from "@/components/admin/connectors/Field";
import { Form, Formik } from "formik";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useToast } from "@/hooks/use-toast";

type GoogleDriveCredentialJsonTypes = "authorized_user" | "service_account";

const DriveJsonUpload = () => {
  const { toast } = useToast();
  const { mutate } = useSWRConfig();
  const [credentialJsonStr, setCredentialJsonStr] = useState<
    string | undefined
  >();

  return (
    <>
      <input
        className={
          "mr-3 text-sm text-gray-900 border border-gray-300 rounded-regular " +
          "cursor-pointer bg-gray-50 dark:text-gray-400 focus:outline-none " +
          "dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400"
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
          let credentialFileType: GoogleDriveCredentialJsonTypes;
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
            toast({
              title: "Error",
              description: `Invalid file provided - ${e}`,
              variant: "destructive",
            });
            return;
          }

          if (credentialFileType === "authorized_user") {
            const response = await fetch(
              "/api/manage/admin/connector/google-drive/app-credential",
              {
                method: "PUT",
                headers: {
                  "Content-Type": "application/json",
                },
                body: credentialJsonStr,
              }
            );
            if (response.ok) {
              toast({
                title: "Success",
                description: "Successfully uploaded app credentials",
                variant: "success",
              });
            } else {
              const errorMsg = await response.text();
              toast({
                title: "Error",
                description: `Failed to upload app credentials - ${errorMsg}`,
                variant: "destructive",
              });
            }
            mutate("/api/manage/admin/connector/google-drive/app-credential");
          }

          if (credentialFileType === "service_account") {
            const response = await fetch(
              "/api/manage/admin/connector/google-drive/service-account-key",
              {
                method: "PUT",
                headers: {
                  "Content-Type": "application/json",
                },
                body: credentialJsonStr,
              }
            );
            if (response.ok) {
              toast({
                title: "Success",
                description: "Successfully uploaded app credentials",
                variant: "success",
              });
            } else {
              const errorMsg = await response.text();
              toast({
                title: "Error",
                description: `Failed to upload app credentials - ${errorMsg}`,
                variant: "destructive",
              });
            }
            mutate(
              "/api/manage/admin/connector/google-drive/service-account-key"
            );
          }
        }}
      >
        Upload
      </Button>
    </>
  );
};

interface DriveJsonUploadSectionProps {
  appCredentialData?: { client_id: string };
  serviceAccountCredentialData?: { service_account_email: string };
}

export const DriveJsonUploadSection = ({
  appCredentialData,
  serviceAccountCredentialData,
}: DriveJsonUploadSectionProps) => {
  const { mutate } = useSWRConfig();
  const { toast } = useToast();

  if (serviceAccountCredentialData?.service_account_email) {
    return (
      <div className="mt-2 text-sm">
        <div>
          Found existing service account key with the following <b>Email:</b>
          <p className="italic mt-1">
            {serviceAccountCredentialData.service_account_email}
          </p>
        </div>
        <div className="mt-4 mb-1">
          If you want to update these credentials, delete the existing
          credentials through the button below, and then upload a new
          credentials JSON.
        </div>
        <Button
          onClick={async () => {
            const response = await fetch(
              "/api/manage/admin/connector/google-drive/service-account-key",
              {
                method: "DELETE",
              }
            );
            if (response.ok) {
              mutate(
                "/api/manage/admin/connector/google-drive/service-account-key"
              );
              toast({
                title: "Success",
                description: "Successfully deleted service account key",
                variant: "success",
              });
            } else {
              const errorMsg = await response.text();
              toast({
                title: "Error",
                description: `Failed to delete service account key - ${errorMsg}`,
                variant: "destructive",
              });
            }
          }}
        >
          Delete
        </Button>
      </div>
    );
  }

  if (appCredentialData?.client_id) {
    return (
      <div className="mt-2 text-sm">
        <div>
          Found existing app credentials with the following <b>Client ID:</b>
          <p className="italic mt-1">{appCredentialData.client_id}</p>
        </div>
        <div className="mt-4 mb-1">
          If you want to update these credentials, delete the existing
          credentials through the button below, and then upload a new
          credentials JSON.
        </div>
        <Button
          onClick={async () => {
            const response = await fetch(
              "/api/manage/admin/connector/google-drive/app-credential",
              {
                method: "DELETE",
              }
            );
            if (response.ok) {
              mutate("/api/manage/admin/connector/google-drive/app-credential");
              toast({
                title: "Success",
                description: "Successfully deleted service account key",
                variant: "success",
              });
            } else {
              const errorMsg = await response.text();
              toast({
                title: "Error",
                description: `Failed to delete app credential - ${errorMsg}`,
                variant: "destructive",
              });
            }
          }}
        >
          Delete
        </Button>
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
          href="https://docs.danswer.dev/connectors/google_drive#authorization"
        >
          here
        </a>{" "}
        to either (1) setup a google OAuth App in your company workspace or (2)
        create a Service Account.
        <br />
        <br />
        Download the credentials JSON if choosing option (1) or the Service
        Account key JSON if chooosing option (2), and upload it here.
      </p>
      <DriveJsonUpload />
    </div>
  );
};

interface DriveCredentialSectionProps {
  googleDrivePublicCredential?: Credential<GoogleDriveCredentialJson>;
  googleDriveServiceAccountCredential?: Credential<GoogleDriveServiceAccountCredentialJson>;
  serviceAccountKeyData?: { service_account_email: string };
  appCredentialData?: { client_id: string };
  refreshCredentials: () => void;
  connectorExists: boolean;
}

export const DriveOAuthSection = ({
  googleDrivePublicCredential,
  googleDriveServiceAccountCredential,
  serviceAccountKeyData,
  appCredentialData,
  refreshCredentials,
  connectorExists,
}: DriveCredentialSectionProps) => {
  const router = useRouter();
  const { toast } = useToast();

  const existingCredential =
    googleDrivePublicCredential || googleDriveServiceAccountCredential;
  if (existingCredential) {
    return (
      <>
        <p className="mb-2 text-sm">
          <i>Existing credential already setup!</i>
        </p>
        <Button
          onClick={async () => {
            if (connectorExists) {
              toast({
                title: "Error",
                description:
                  "Cannot revoke access to Google Drive while any connector is still setup. Please delete all connectors, then try again.",
                variant: "destructive",
              });
              return;
            }
            await adminDeleteCredential(existingCredential.id);
            toast({
              title: "Success",
              description: "Successfully revoked access to Google Drive!",
              variant: "success",
            });
            refreshCredentials();
          }}
        >
          Revoke Access
        </Button>
      </>
    );
  }

  if (serviceAccountKeyData?.service_account_email) {
    return (
      <div>
        <p className="text-sm mb-2">
          When using a Google Drive Service Account, you can either have enMedD
          AI act as the service account itself OR you can specify an account for
          the service account to impersonate.
          <br />
          <br />
          If you want to use the service account itself, leave the{" "}
          <b>&apos;User email to impersonate&apos;</b> field blank when
          submitting. If you do choose this option, make sure you have shared
          the documents you want to index with the service account.
        </p>

        <Card>
          <CardContent>
            <Formik
              initialValues={{
                google_drive_delegated_user: "",
              }}
              validationSchema={Yup.object().shape({
                google_drive_delegated_user: Yup.string().optional(),
              })}
              onSubmit={async (values, formikHelpers) => {
                formikHelpers.setSubmitting(true);

                const response = await fetch(
                  "/api/manage/admin/connector/google-drive/service-account-credential",
                  {
                    method: "PUT",
                    headers: {
                      "Content-Type": "application/json",
                    },
                    body: JSON.stringify({
                      google_drive_delegated_user:
                        values.google_drive_delegated_user,
                    }),
                  }
                );

                if (response.ok) {
                  toast({
                    title: "Success",
                    description:
                      "Successfully created service account credential",
                    variant: "success",
                  });
                } else {
                  const errorMsg = await response.text();
                  toast({
                    title: "Error",
                    description: `Failed to create service account credential - ${errorMsg}`,
                    variant: "destructive",
                  });
                }
                refreshCredentials();
              }}
            >
              {({ isSubmitting }) => (
                <Form>
                  <TextFormField
                    name="google_drive_delegated_user"
                    label="[Optional] User email to impersonate:"
                    subtext="If left blank, enMedD AI will use the service account itself."
                  />
                  <div className="flex">
                    <button
                      type="submit"
                      disabled={isSubmitting}
                      className={
                        "bg-slate-500 hover:bg-slate-700 text-inverted " +
                        "font-bold py-2 px-4 rounded focus:outline-none " +
                        "focus:shadow-outline w-full max-w-sm mx-auto"
                      }
                    >
                      Submit
                    </button>
                  </div>
                </Form>
              )}
            </Formik>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (appCredentialData?.client_id) {
    return (
      <div className="text-sm mb-4">
        <p className="mb-2">
          Next, you must provide credentials via OAuth. This gives us read
          access to the docs you have access to in your google drive account.
        </p>
        <Button
          onClick={async () => {
            const [authUrl, errorMsg] = await setupGoogleDriveOAuth({
              isAdmin: true,
            });
            if (authUrl) {
              // cookie used by callback to determine where to finally redirect to
              Cookies.set(GOOGLE_DRIVE_AUTH_IS_ADMIN_COOKIE_NAME, "true", {
                path: "/",
              });
              router.push(authUrl);
              return;
            }

            toast({
              title: "Error",
              description: errorMsg,
              variant: "destructive",
            });
          }}
        >
          Authenticate with Google Drive
        </Button>
      </div>
    );
  }

  // case where no keys have been uploaded in step 1
  return (
    <p className="text-sm">
      Please upload either a OAuth Client Credential JSON or a Google Drive
      Service Account Key JSON in Step 1 before moving onto Step 2.
    </p>
  );
};
