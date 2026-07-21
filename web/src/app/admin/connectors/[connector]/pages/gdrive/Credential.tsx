import React, { useState, useEffect } from "react";
import * as Yup from "yup";
import { useRouter } from "next/navigation";
import type { Route } from "next";
import { setupGoogleDriveOAuth } from "@/lib/googleDrive";
import { DOCS_ADMINS_PATH } from "@/lib/constants";
import { Form, Formik } from "formik";
import { User } from "@/lib/types";
import { Button, Text } from "@opal/components";
import { Section, toast } from "@opal/layouts";
import InputFile from "@/refresh-components/inputs/InputFile";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import {
  parseOauthAppCredentialJson,
  refreshAllGoogleData,
} from "@/lib/googleConnector";
import { ValidSources } from "@/lib/types";
import { markdown } from "@opal/utils";

interface DriveCredentialSectionProps {
  refreshCredentials: () => void;
  user: User | null;
}

export const DriveAuthSection = ({
  refreshCredentials,
  user,
}: DriveCredentialSectionProps) => {
  const router = useRouter();
  const [isAuthenticating, setIsAuthenticating] = useState(false);
  const [justCreated, setJustCreated] = useState(false);
  const [serviceAccountKey, setServiceAccountKey] = useState<Record<
    string,
    unknown
  > | null>(null);
  const [oauthAppCredential, setOauthAppCredential] = useState<Record<
    string,
    unknown
  > | null>(null);
  // Confirm only a credential created in this session. A pre-existing one must
  // not gate the form, or a second could never be created. Revoke is in the list.
  if (justCreated) {
    return (
      <Section
        alignItems="start"
        justifyContent="start"
        gap={0.25}
        className="mt-4 rounded-sm border border-border-02 bg-background-tint-02 px-4 py-3"
      >
        <Text as="p" font="main-ui-action">
          Authentication Complete
        </Text>
        <Text as="p" font="secondary-body" color="text-03">
          Your Google Drive credential was created. Manage or revoke it from the
          credential list.
        </Text>
      </Section>
    );
  }

  return (
    <Section alignItems="start" justifyContent="start" gap={1}>
      <Text as="h3" font="heading-h2">
        Google Drive Authentication
      </Text>
      <Section alignItems="start" justifyContent="start" gap={1}>
        <Text as="p" font="main-ui-action">
          Option 1: OAuth app
        </Text>
        <Text as="p" font="secondary-body" color="text-03">
          {markdown(
            `Upload the OAuth app JSON from Google Cloud Console ([setup instructions](${DOCS_ADMINS_PATH}/connectors/official/google_drive/overview)), then authenticate with the Google account whose Drive you want to index.`
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
        <Section flexDirection="row" justifyContent="end">
          <Button
            disabled={!oauthAppCredential || isAuthenticating}
            onClick={async () => {
              if (!oauthAppCredential) {
                return;
              }
              setIsAuthenticating(true);
              try {
                const [authUrl, errorMsg] = await setupGoogleDriveOAuth({
                  isAdmin: true,
                  name: "OAuth (uploaded)",
                  appCredential: oauthAppCredential,
                });
                if (authUrl) {
                  router.push(authUrl as Route);
                } else {
                  toast.error(errorMsg);
                  setIsAuthenticating(false);
                }
              } catch (error) {
                toast.error(
                  `Failed to authenticate with Google Drive - ${error}`
                );
                setIsAuthenticating(false);
              }
            }}
          >
            {isAuthenticating
              ? "Authenticating..."
              : "Authenticate with Google Drive"}
          </Button>
        </Section>
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
                "/api/manage/admin/connector/google-drive/service-account-credential",
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
                setJustCreated(true);
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
            <Form className="w-full">
              <Section alignItems="start" justifyContent="start" gap={0.25}>
                <Text font="main-ui-body" color="text-03">
                  Primary Admin Email
                </Text>
                <InputTypeInField
                  name="google_primary_admin"
                  placeholder="admin@yourcompany.com"
                />
                <Text font="secondary-body" color="text-03">
                  Enter the email of an admin or owner of the Google
                  Organization that owns the Google Drive(s) you want to index.
                </Text>
              </Section>
              <Section
                flexDirection="row"
                justifyContent="end"
                className="pt-2"
              >
                <Button disabled={isSubmitting} type="submit">
                  {isSubmitting ? "Creating..." : "Create Credential"}
                </Button>
              </Section>
            </Form>
          )}
        </Formik>
      </Section>
    </Section>
  );
};
