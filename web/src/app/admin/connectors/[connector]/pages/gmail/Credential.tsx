import { Button, Text } from "@opal/components";
import { Section, toast } from "@opal/layouts";
import InputFile from "@/refresh-components/inputs/InputFile";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import React, { useState, useEffect } from "react";
import { useTranslations } from "next-intl";
import * as Yup from "yup";
import { useRouter } from "next/navigation";
import type { Route } from "next";
import { setupGmailOAuth } from "@/lib/gmail";
import { DOCS_ADMINS_PATH } from "@/lib/constants";
import { CRAFT_OAUTH_COOKIE_NAME } from "@/app/craft/v1/constants";
import Cookies from "js-cookie";
import { Form, Formik } from "formik";
import { User } from "@/lib/types";
import {
  parseOauthAppCredentialJson,
  refreshAllGoogleData,
} from "@/lib/googleConnector";
import { ValidSources } from "@/lib/types";
import { markdown } from "@opal/utils";

interface GmailCredentialSectionProps {
  refreshCredentials: () => void;
  user: User | null;
  buildMode?: boolean;
  onOAuthRedirect?: () => void;
}

export const GmailAuthSection = ({
  refreshCredentials,
  user,
  buildMode = false,
  onOAuthRedirect,
}: GmailCredentialSectionProps) => {
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
          {t("gmail.authComplete.title")}
        </Text>
        <Text as="p" font="secondary-body" color="text-03">
          {t("gmail.authComplete.description")}
        </Text>
      </Section>
    );
  }

  return (
    <Section alignItems="start" justifyContent="start" gap={4}>
      <Text as="h3" font="heading-h2">
        {t("gmail.section.title")}
      </Text>
      <Section alignItems="start" justifyContent="start" gap={4}>
        <Text as="p" font="main-ui-action">
          {t("gmail.oauthOption.title")}
        </Text>
        <Text as="p" font="secondary-body" color="text-03">
          {markdown(
            t("gmail.oauthOption.description", {
              docsUrl: `${DOCS_ADMINS_PATH}/connectors/official/gmail/overview`,
            })
          )}
        </Text>
        <InputFile
          accept="application/json"
          placeholder={t("gmail.oauthUpload.placeholder")}
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
                toast.error(
                  t("gmail.authFailed.toast", { error: String(error) })
                );
                setIsAuthenticating(false);
              }
            }}
          >
            {isAuthenticating
              ? t("gmail.authenticateButton.pendingLabel")
              : t("gmail.authenticateButton.label")}
          </Button>
        </Section>
        <Text as="p" font="main-ui-action">
          {t("gmail.serviceAccountOption.title")}
        </Text>
        <InputFile
          accept="application/json"
          placeholder={t("gmail.serviceAccountUpload.placeholder")}
          setValue={(value) => {
            if (!value) {
              setServiceAccountKey(null);
              return;
            }
            try {
              const parsed = JSON.parse(value) as Record<string, unknown>;
              if (parsed.type !== "service_account") {
                toast.error(t("gmail.invalidServiceAccountFile.toast"));
                setServiceAccountKey(null);
                return;
              }
              setServiceAccountKey(parsed);
            } catch (error) {
              toast.error(
                t("gmail.invalidFile.toast", { error: String(error) })
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
              .email(t("gmail.primaryAdmin.invalidEmail"))
              .required(t("gmail.primaryAdmin.required")),
          })}
          onSubmit={async (values, formikHelpers) => {
            formikHelpers.setSubmitting(true);

            if (!serviceAccountKey) {
              toast.error(t("gmail.missingServiceAccountKey.toast"));
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
                toast.success(t("gmail.serviceAccountCreated.toast"));
                setJustCreated(true);
                refreshCredentials();
              } else {
                const errorMsg = await response.text();
                toast.error(
                  t("gmail.serviceAccountCreateFailed.toast", {
                    error: errorMsg,
                  })
                );
              }
            } catch (error) {
              toast.error(
                t("gmail.serviceAccountCreateFailed.toast", {
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
                  {t("gmail.primaryAdmin.label")}
                </Text>
                <InputTypeInField
                  name="google_primary_admin"
                  placeholder="admin@yourcompany.com"
                />
                <Text font="secondary-body" color="text-03">
                  {t("gmail.primaryAdmin.description")}
                </Text>
              </Section>
              <Section
                flexDirection="row"
                justifyContent="end"
                className="pt-2"
              >
                <Button disabled={isSubmitting} type="submit">
                  {isSubmitting
                    ? t("gmail.createButton.pendingLabel")
                    : t("gmail.createButton.label")}
                </Button>
              </Section>
            </Form>
          )}
        </Formik>
      </Section>
    </Section>
  );
};
