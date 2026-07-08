import { Button, Text } from "@opal/components";
import InputFile from "@/refresh-components/inputs/InputFile";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import { toast } from "@/hooks/useToast";
import React, { useState, useEffect } from "react";
import * as Yup from "yup";
import { useRouter } from "next/navigation";
import type { Route } from "next";
import { adminDeleteCredential } from "@/lib/credential";
import { setupGmailOAuth } from "@/lib/gmail";
import { DOCS_ADMINS_PATH } from "@/lib/constants";
import { CRAFT_OAUTH_COOKIE_NAME } from "@/app/craft/v1/constants";
import Cookies from "js-cookie";
import { Form, Formik } from "formik";
import { User } from "@/lib/types";
import {
  Credential,
  GmailCredentialJson,
  GmailServiceAccountCredentialJson,
} from "@/lib/connectors/credentials";
import {
  parseOauthAppCredentialJson,
  refreshAllGoogleData,
} from "@/lib/googleConnector";
import { ValidSources } from "@/lib/types";
import { FiCheck } from "react-icons/fi";
import { markdown } from "@opal/utils";
import { Section } from "@/layouts/general-layouts";

interface GmailCredentialSectionProps {
  gmailPublicCredential?: Credential<GmailCredentialJson>;
  gmailServiceAccountCredential?: Credential<GmailServiceAccountCredentialJson>;
  refreshCredentials: () => void;
  connectorExists: boolean;
  user: User | null;
  buildMode?: boolean;
  onOAuthRedirect?: () => void;
  onCredentialCreated?: (
    credential: Credential<
      GmailCredentialJson | GmailServiceAccountCredentialJson
    >
  ) => void;
}

async function handleRevokeAccess(
  connectorExists: boolean,
  existingCredential:
    | Credential<GmailCredentialJson>
    | Credential<GmailServiceAccountCredentialJson>,
  refreshCredentials: () => void
) {
  if (connectorExists) {
    const message =
      "Cannot revoke the Gmail credential while any connector is still associated with the credential. " +
      "Please delete all associated connectors, then try again.";
    toast.error(message);
    return;
  }

  await adminDeleteCredential(existingCredential.id);
  toast.success("Successfully revoked the Gmail credential!");

  refreshCredentials();
}

export const GmailAuthSection = ({
  gmailPublicCredential,
  gmailServiceAccountCredential,
  refreshCredentials,
  connectorExists,
  user,
  buildMode = false,
  onOAuthRedirect,
  onCredentialCreated,
}: GmailCredentialSectionProps) => {
  const router = useRouter();
  const [isAuthenticating, setIsAuthenticating] = useState(false);
  const [serviceAccountKey, setServiceAccountKey] = useState<Record<
    string,
    unknown
  > | null>(null);
  const [oauthAppCredential, setOauthAppCredential] = useState<Record<
    string,
    unknown
  > | null>(null);
  const [localGmailPublicCredential, setLocalGmailPublicCredential] = useState(
    gmailPublicCredential
  );
  const [
    localGmailServiceAccountCredential,
    setLocalGmailServiceAccountCredential,
  ] = useState(gmailServiceAccountCredential);

  // Update local state when props change
  useEffect(() => {
    setLocalGmailPublicCredential(gmailPublicCredential);
    setLocalGmailServiceAccountCredential(gmailServiceAccountCredential);
  }, [gmailPublicCredential, gmailServiceAccountCredential]);

  const existingCredential =
    localGmailPublicCredential || localGmailServiceAccountCredential;
  if (existingCredential) {
    return (
      <div className="w-full">
        <div className="mt-4">
          <div className="py-3 px-4 bg-blue-50/30 dark:bg-blue-900/5 rounded-sm mb-4 flex items-start">
            <FiCheck className="text-blue-500 h-5 w-5 mr-2 mt-0.5 shrink-0" />
            <div className="flex-1">
              <span className="font-medium block">Authentication Complete</span>
              <p className="text-sm mt-1 text-text-500 dark:text-text-400 wrap-break-word">
                Your Gmail credentials have been successfully uploaded and
                authenticated.
              </p>
            </div>
          </div>
          <Section flexDirection="row" justifyContent="between" height="fit">
            <Button
              variant="danger"
              onClick={async () => {
                handleRevokeAccess(
                  connectorExists,
                  existingCredential,
                  refreshCredentials
                );
              }}
            >
              Revoke Access
            </Button>
            {buildMode && onCredentialCreated && (
              <Button onClick={() => onCredentialCreated(existingCredential)}>
                Continue
              </Button>
            )}
          </Section>
        </div>
      </div>
    );
  }

  return (
    <div className="w-full">
      <Text as="h3" font="heading-h2">
        Gmail Authentication
      </Text>
      <div className="mt-4 w-full space-y-4">
        <Text as="p" font="main-ui-action">
          Option 1: OAuth app
        </Text>
        <Text as="p" font="secondary-body" color="text-03">
          {markdown(
            `Upload the OAuth app JSON from Google Cloud Console ([setup instructions](${DOCS_ADMINS_PATH}/connectors/official/gmail/overview)), then authenticate with the Google account whose Gmail you want to index.`
          )}
        </Text>
        <InputFile
          accept="application/json"
          placeholder="Upload or paste your OAuth app JSON"
          setValue={(value) => {
            setOauthAppCredential(
              value ? parseOauthAppCredentialJson(value) : null
            );
          }}
        />
        <div className="flex w-full justify-end">
          <Button
            disabled={!oauthAppCredential || isAuthenticating}
            onClick={async () => {
              if (!oauthAppCredential) {
                return;
              }
              setIsAuthenticating(true);
              try {
                if (buildMode) {
                  Cookies.set(CRAFT_OAUTH_COOKIE_NAME, "true", {
                    path: "/",
                  });
                }
                const [authUrl, errorMsg] = await setupGmailOAuth({
                  isAdmin: true,
                  appCredential: oauthAppCredential,
                });
                if (authUrl) {
                  onOAuthRedirect?.();
                  router.push(authUrl as Route);
                } else {
                  toast.error(errorMsg);
                  setIsAuthenticating(false);
                }
              } catch (error) {
                toast.error(`Failed to authenticate with Gmail - ${error}`);
                setIsAuthenticating(false);
              }
            }}
          >
            {isAuthenticating ? "Authenticating..." : "Authenticate with Gmail"}
          </Button>
        </div>
        <Text as="p" font="main-ui-action">
          Option 2: Service account
        </Text>
        <InputFile
          accept="application/json"
          placeholder="Upload or paste your service account JSON key"
          setValue={(value) => {
            if (!value) {
              setServiceAccountKey(null);
              return;
            }
            try {
              const parsed = JSON.parse(value) as Record<string, unknown>;
              if (parsed.type !== "service_account") {
                toast.error(
                  "Invalid file provided - expected a Service Account JSON key"
                );
                setServiceAccountKey(null);
                return;
              }
              setServiceAccountKey(parsed);
            } catch (error) {
              toast.error(`Invalid file provided - ${error}`);
              setServiceAccountKey(null);
            }
          }}
        />

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

            if (!serviceAccountKey) {
              toast.error(
                "Please upload a service account key before creating a credential"
              );
              formikHelpers.setSubmitting(false);
              return;
            }

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
                    service_account_key: serviceAccountKey,
                  }),
                }
              );

              if (response.ok) {
                toast.success(
                  "Successfully created service account credential"
                );
                refreshCredentials();
              } else {
                const errorMsg = await response.text();
                toast.error(
                  `Failed to create service account credential - ${errorMsg}`
                );
              }
            } catch (error) {
              toast.error(
                `Failed to create service account credential - ${error}`
              );
            } finally {
              formikHelpers.setSubmitting(false);
            }
          }}
        >
          {({ isSubmitting }) => (
            <Form>
              <div className="w-full space-y-1">
                <Text font="main-ui-body" color="text-03">
                  Primary Admin Email
                </Text>
                <InputTypeInField
                  name="google_primary_admin"
                  placeholder="admin@yourcompany.com"
                />
                <Text font="secondary-body" color="text-03">
                  Enter the email of an admin or owner of the Google
                  Organization that owns the Gmail account(s) you want to index.
                </Text>
              </div>
              <div className="flex w-full justify-end pt-2">
                <Button disabled={isSubmitting} type="submit">
                  {isSubmitting ? "Creating..." : "Create Credential"}
                </Button>
              </div>
            </Form>
          )}
        </Formik>
      </div>
    </div>
  );
};
