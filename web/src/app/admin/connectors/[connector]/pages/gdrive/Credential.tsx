import React, { useState, useEffect } from "react";
import { useTranslations } from "next-intl";
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
  const t = useTranslations("admin.connectorsList");
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
        gap={1}
        className="mt-4 rounded-sm border border-border-02 bg-background-tint-02 px-4 py-3"
      >
        <Text as="p" font="main-ui-action">
          {t("gdrive.authComplete.title")}
        </Text>
        <Text as="p" font="secondary-body" color="text-03">
          {t("gdrive.authComplete.description")}
        </Text>
      </Section>
    );
  }

  return (
    <Section alignItems="start" justifyContent="start" gap={4}>
      <Text as="h3" font="heading-h2">
        {t("gdrive.section.title")}
      </Text>
      <Section alignItems="start" justifyContent="start" gap={4}>
        <Text as="p" font="main-ui-action">
          {t("gdrive.oauthOption.title")}
        </Text>
        <Text as="p" font="secondary-body" color="text-03">
          {markdown(
            t("gdrive.oauthOption.description", {
              docsUrl: `${DOCS_ADMINS_PATH}/connectors/official/google_drive/overview`,
            })
          )}
        </Text>
        <InputFile
          accept="application/json"
          placeholder={t("gdrive.oauthUpload.placeholder")}
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
                  t("gdrive.authFailed.toast", { error: String(error) })
                );
                setIsAuthenticating(false);
              }
            }}
          >
            {isAuthenticating
              ? t("gdrive.authenticateButton.pendingLabel")
              : t("gdrive.authenticateButton.label")}
          </Button>
        </Section>
        <Text as="p" font="main-ui-action">
          {t("gdrive.serviceAccountOption.title")}
        </Text>
        <InputFile
          accept="application/json"
          placeholder={t("gdrive.serviceAccountUpload.placeholder")}
          setValue={(value) => {
            if (!value) {
              setServiceAccountKey(null);
              return;
            }
            try {
              const parsed = JSON.parse(value) as Record<string, unknown>;
              if (parsed.type !== "service_account") {
                toast.error(t("gdrive.invalidServiceAccountFile.toast"));
                setServiceAccountKey(null);
                return;
              }
              setServiceAccountKey(parsed);
            } catch (error) {
              toast.error(
                t("gdrive.invalidFile.toast", { error: String(error) })
              );
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
              .email(t("gdrive.primaryAdmin.invalidEmail"))
              .required(t("gdrive.primaryAdmin.required")),
          })}
          onSubmit={async (values, formikHelpers) => {
            formikHelpers.setSubmitting(true);

            if (!serviceAccountKey) {
              toast.error(t("gdrive.missingServiceAccountKey.toast"));
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
                toast.success(t("gdrive.serviceAccountCreated.toast"));
                setJustCreated(true);
                refreshCredentials();
              } else {
                const errorMsg = await response.text();
                toast.error(
                  t("gdrive.serviceAccountCreateFailed.toast", {
                    error: errorMsg,
                  })
                );
              }
            } catch (error) {
              toast.error(
                t("gdrive.serviceAccountCreateFailed.toast", {
                  error: String(error),
                })
              );
            } finally {
              formikHelpers.setSubmitting(false);
            }
          }}
        >
          {({ isSubmitting }) => (
            <Form className="w-full">
              <Section alignItems="start" justifyContent="start" gap={1}>
                <Text font="main-ui-body" color="text-03">
                  {t("gdrive.primaryAdmin.label")}
                </Text>
                <InputTypeInField
                  name="google_primary_admin"
                  placeholder="admin@yourcompany.com"
                />
                <Text font="secondary-body" color="text-03">
                  {t("gdrive.primaryAdmin.description")}
                </Text>
              </Section>
              <Section
                flexDirection="row"
                justifyContent="end"
                className="pt-2"
              >
                <Button disabled={isSubmitting} type="submit">
                  {isSubmitting
                    ? t("gdrive.createButton.pendingLabel")
                    : t("gdrive.createButton.label")}
                </Button>
              </Section>
            </Form>
          )}
        </Formik>
      </Section>
    </Section>
  );
};
