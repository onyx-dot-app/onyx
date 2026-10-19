"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import { useFormikContext } from "formik";
import * as Yup from "yup";
import {
  Card,
  CopyButton,
  Divider,
  InputKeyValue,
  InputPasswordTypeIn,
  InputSingleSelect,
  InputSwitch,
  InputTypeIn,
  MessageCard,
  type SelectOption,
} from "@opal/components";
import { Content, InputPadder, Section } from "@opal/layouts";
import { FormField } from "@/refresh-components/form/FormField";
import Text from "@/refresh-components/texts/Text";
import { MASKED_OAUTH_CREDENTIAL } from "@/lib/oauth/config";
import type {
  AuthMethod,
  OpenAPIPluginFormValues,
} from "@/lib/plugins/openapi/types";
import OAuthPKCESupport from "@/sections/actions/oauth/OAuthPKCESupport";
import OAuthConnectionCheck from "@/sections/actions/oauth/OAuthConnectionCheck";
import { useOAuthPassThroughEnabled } from "@/lib/auth/hooks";
import { useSettings } from "@/lib/settings/hooks";

/**
 * The auth rules of the OpenAPI form. Saved OAuth client credentials may stay
 * masked; new ones are required.
 */
export function useOpenApiAuthSchema(isEditingOAuthConfig: boolean) {
  const t = useTranslations("actions");
  return useMemo(() => {
    const oauthUrl = (required: string) =>
      Yup.string().when("authMethod", {
        is: "oauth",
        then: (schema) =>
          schema
            .url(t("openApiAuthModal.errors.invalidUrl"))
            .required(required),
        otherwise: (schema) => schema.notRequired(),
      });
    const oauthCredential = (required: string) =>
      Yup.string().when("authMethod", {
        is: "oauth",
        then: (schema) =>
          isEditingOAuthConfig
            ? schema.optional()
            : schema
                .notOneOf([MASKED_OAUTH_CREDENTIAL], required)
                .required(required),
        otherwise: (schema) => schema.notRequired(),
      });
    return Yup.object({
      authMethod: Yup.mixed<AuthMethod>()
        .oneOf(["oauth", "pt-oauth", "custom-header", "none"])
        .required(t("openApiAuthModal.authMethod.required")),
      authorizationUrl: oauthUrl(
        t("openApiAuthModal.authorizationUrl.required")
      ),
      tokenUrl: oauthUrl(t("openApiAuthModal.tokenUrl.required")),
      clientId: oauthCredential(t("openApiAuthModal.clientId.required")),
      clientSecret: oauthCredential(
        t("openApiAuthModal.clientSecret.required")
      ),
      scopes: Yup.string().notRequired(),
      headers: Yup.array().when("authMethod", {
        is: "custom-header",
        then: () =>
          Yup.array()
            .of(
              Yup.object({
                key: Yup.string().required(
                  t("openApiAuthModal.headers.keyRequired")
                ),
                value: Yup.string().required(
                  t("openApiAuthModal.headers.valueRequired")
                ),
              })
            )
            .min(1, t("openApiAuthModal.headers.minRequired")),
        otherwise: () =>
          Yup.array().of(
            Yup.object({ key: Yup.string(), value: Yup.string() })
          ),
      }),
    });
  }, [isEditingOAuthConfig, t]);
}

interface OpenAPIAuthFieldsProps {
  /** The plugin already has an OAuth configuration. */
  oauthConfigId: number | null;
  /** The saved OAuth configuration could not be loaded. */
  oauthConfigError: boolean;
  disabled: boolean;
}

/** The OpenAPI modal's Authentication tab: how the plugin's calls authenticate. */
export default function OpenAPIAuthFields({
  oauthConfigId,
  oauthConfigError,
  disabled,
}: OpenAPIAuthFieldsProps) {
  const t = useTranslations("actions");
  const { appName } = useSettings();
  const isOAuthEnabled = useOAuthPassThroughEnabled();
  const {
    values,
    errors,
    touched,
    handleChange,
    setFieldValue,
    setFieldError,
  } = useFormikContext<OpenAPIPluginFormValues>();
  const auth = values.auth;
  const authErrors = errors.auth;
  const authTouched = touched.auth;
  const isEditingOAuthConfig = oauthConfigId !== null;
  const redirectUri =
    typeof window === "undefined"
      ? "https://{YOUR_DOMAIN}/oauth-config/callback"
      : `${window.location.origin}/oauth-config/callback`;

  function fieldState(field: keyof OpenAPIPluginFormValues["auth"]) {
    if (authErrors?.[field] && authTouched?.[field]) return "error";
    return authTouched?.[field] ? "success" : "idle";
  }

  const methodOptions: SelectOption[] = [
    {
      value: "oauth",
      title: t("openApiAuthModal.authMethod.oauth.label"),
      description: t("openApiAuthModal.authMethod.oauth.description"),
    },
    ...(isOAuthEnabled
      ? [
          {
            value: "pt-oauth",
            title: t("openApiAuthModal.authMethod.ptOauth.label"),
            description: t("openApiAuthModal.authMethod.ptOauth.description", {
              appName,
            }),
          },
        ]
      : []),
    {
      value: "custom-header",
      title: t("openApiAuthModal.authMethod.customHeader.label"),
      description: t("openApiAuthModal.authMethod.customHeader.description"),
    },
  ];

  return (
    <fieldset disabled={disabled} className="contents">
      {oauthConfigError && (
        <InputPadder>
          <Text as="p" mainUiBody className="text-action-text-danger-05">
            {t("openApiAuthModal.errors.loadConfigFailed")}
          </Text>
        </InputPadder>
      )}

      <InputPadder>
        <FormField name="auth.authMethod" state={fieldState("authMethod")}>
          <FormField.Label>
            {t("openApiAuthModal.authMethod.label")}
          </FormField.Label>
          <FormField.Control asChild>
            <InputSingleSelect
              value={auth.authMethod}
              onValueChange={(value) =>
                void setFieldValue("auth.authMethod", value)
              }
              defaultOption="none"
              placeholder={t("openApiAuthModal.authMethod.placeholder")}
              options={[
                {
                  value: "none",
                  title: t("openApiAuthModal.authMethod.none.label"),
                },
                {
                  title: t("openApiAuthModal.authMethod.optionsTitle"),
                  options: methodOptions,
                },
              ]}
            />
          </FormField.Control>
          <FormField.Message messages={{ error: authErrors?.authMethod }} />
        </FormField>
      </InputPadder>

      {(auth.authMethod === "oauth" || auth.authMethod === "custom-header") && (
        <Divider paddingParallel={2} paddingPerpendicular={2} />
      )}

      {auth.authMethod === "oauth" && (
        <Card padding={2}>
          <Section alignItems="stretch" height="fit" gap={4}>
            <FormField
              name="auth.authorizationUrl"
              state={fieldState("authorizationUrl")}
            >
              <FormField.Label>
                {t("openApiAuthModal.authorizationUrl.label")}
              </FormField.Label>
              <FormField.Control asChild>
                <InputTypeIn
                  name="auth.authorizationUrl"
                  value={auth.authorizationUrl}
                  onChange={handleChange}
                  placeholder={t("placeholders.oauthAuthorizationUrl")}
                />
              </FormField.Control>
              <FormField.Message
                messages={{ error: authErrors?.authorizationUrl }}
              />
            </FormField>

            <FormField name="auth.tokenUrl" state={fieldState("tokenUrl")}>
              <FormField.Label>
                {t("openApiAuthModal.tokenUrl.label")}
              </FormField.Label>
              <FormField.Control asChild>
                <InputTypeIn
                  name="auth.tokenUrl"
                  value={auth.tokenUrl}
                  onChange={handleChange}
                  placeholder={t("placeholders.oauthTokenUrl")}
                />
              </FormField.Control>
              <OAuthPKCESupport
                authorizationUrl={auth.authorizationUrl}
                tokenUrl={auth.tokenUrl}
              />
              <FormField.Message messages={{ error: authErrors?.tokenUrl }} />
            </FormField>

            <FormField name="auth.clientId" state={fieldState("clientId")}>
              <FormField.Label>
                {t("openApiAuthModal.clientId.label")}
              </FormField.Label>
              <FormField.Control asChild>
                <InputTypeIn
                  name="auth.clientId"
                  value={auth.clientId}
                  onChange={handleChange}
                  placeholder=" "
                />
              </FormField.Control>
              {isEditingOAuthConfig && (
                <FormField.Description>
                  {t("openApiAuthModal.clientId.description")}
                </FormField.Description>
              )}
              <FormField.Message messages={{ error: authErrors?.clientId }} />
            </FormField>

            <FormField
              name="auth.clientSecret"
              state={fieldState("clientSecret")}
            >
              <FormField.Label>
                {t("openApiAuthModal.clientSecret.label")}
              </FormField.Label>
              <FormField.Control asChild>
                <InputPasswordTypeIn
                  name="auth.clientSecret"
                  value={auth.clientSecret}
                  onChange={handleChange}
                  placeholder=" "
                />
              </FormField.Control>
              {isEditingOAuthConfig && (
                <FormField.Description>
                  {t("openApiAuthModal.clientSecret.description")}
                </FormField.Description>
              )}
              <FormField.Message
                messages={{ error: authErrors?.clientSecret }}
              />
            </FormField>

            <FormField name="auth.scopes" state={fieldState("scopes")}>
              <FormField.Label>
                {t.rich("openApiAuthModal.scopes.label", {
                  optional: (chunks) => (
                    <span className="text-text-03">{chunks}</span>
                  ),
                })}
              </FormField.Label>
              <FormField.Control asChild>
                <InputTypeIn
                  name="auth.scopes"
                  value={auth.scopes}
                  onChange={handleChange}
                  placeholder={t("openApiAuthModal.scopes.placeholder")}
                />
              </FormField.Control>
              <FormField.Description>
                {t("openApiAuthModal.scopes.description")}
              </FormField.Description>
              <FormField.Message messages={{ error: authErrors?.scopes }} />
            </FormField>

            <FormField name="auth.supportsPkce">
              <div className="flex items-start justify-between gap-4">
                <div className="flex flex-col gap-1">
                  <FormField.Label>
                    {t("openApiAuthModal.pkce.label")}
                  </FormField.Label>
                  <FormField.Description>
                    {t("openApiAuthModal.pkce.description")}
                  </FormField.Description>
                </div>
                <FormField.Control asChild>
                  <InputSwitch
                    checked={auth.supportsPkce}
                    onCheckedChange={(checked) =>
                      void setFieldValue("auth.supportsPkce", checked)
                    }
                  />
                </FormField.Control>
              </div>
            </FormField>

            <OAuthConnectionCheck
              values={auth}
              configId={oauthConfigId}
              disabled={disabled || Boolean(authErrors)}
            />

            <div className="flex flex-col gap-3 rounded-12 bg-background-tint-01 p-3">
              <div className="flex flex-col gap-2 w-full">
                <Text
                  as="p"
                  text03
                  secondaryBody
                  className="flex flex-wrap gap-1"
                >
                  {t.rich("openApiAuthModal.redirectUri.label", {
                    emphasis: (chunks) => (
                      <span className="font-secondary-action">{chunks}</span>
                    ),
                  })}
                </Text>
                <div className="flex items-center gap-2 rounded-08 border border-border-01 bg-background-tint-00 px-3 py-2">
                  <Text
                    as="p"
                    text04
                    className="font-mono text-[12px] leading-[16px] truncate flex-1"
                  >
                    {redirectUri}
                  </Text>
                  <CopyButton
                    getCopyText={() => redirectUri}
                    tooltip={t("openApiAuthModal.redirectUri.copyTooltip")}
                    prominence="tertiary"
                    size="sm"
                  />
                </div>
              </div>
            </div>
          </Section>
        </Card>
      )}

      {auth.authMethod === "custom-header" && (
        <Card padding={2}>
          <Section alignItems="stretch" height="fit" gap={2}>
            <Content
              sizePreset="main-ui"
              variant="section"
              title={t("openApiAuthModal.headers.title")}
              description={t("openApiAuthModal.headers.description")}
            />
            <FormField
              name="auth.headers"
              state={authErrors?.headers ? "error" : "idle"}
            >
              <FormField.Control asChild>
                <InputKeyValue
                  keyTitle={t("openApiAuthModal.headers.keyTitle")}
                  valueTitle={t("openApiAuthModal.headers.valueTitle")}
                  items={auth.headers}
                  onChange={(items) =>
                    void setFieldValue("auth.headers", items)
                  }
                  addButtonLabel={t("openApiAuthModal.headers.addButton.label")}
                  onValidationError={(message) =>
                    setFieldError("auth.headers", message || undefined)
                  }
                  layout="equal"
                  hideTitles
                />
              </FormField.Control>
              <FormField.Message
                messages={{
                  error:
                    typeof authErrors?.headers === "string"
                      ? authErrors.headers
                      : undefined,
                }}
              />
            </FormField>
          </Section>
        </Card>
      )}

      {auth.authMethod === "pt-oauth" && (
        <MessageCard
          outerPadding={1}
          innerPadding={1}
          title={t("openApiAuthModal.passThroughNotice.title")}
          description={t("openApiAuthModal.passThroughNotice.description", {
            appName,
          })}
        />
      )}
    </fieldset>
  );
}
