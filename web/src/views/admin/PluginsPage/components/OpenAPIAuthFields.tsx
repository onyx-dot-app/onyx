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
  InputTypeIn,
  MessageCard,
  type SelectOption,
} from "@opal/components";
import {
  Content,
  InputHorizontal,
  InputPadder,
  InputVertical,
  Section,
} from "@opal/layouts";
import { InputSwitchField } from "@opal/form";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
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
        <InputVertical
          withLabel="auth.authMethod"
          title={t("openApiAuthModal.authMethod.label")}
        >
          <InputSingleSelect
            id="auth.authMethod"
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
                suffix: t("openApiAuthModal.authMethod.none.suffix"),
              },
              {
                title: t("openApiAuthModal.authMethod.optionsTitle"),
                options: methodOptions,
              },
            ]}
          />
        </InputVertical>
      </InputPadder>

      <Divider paddingParallel={2} paddingPerpendicular={2} />

      {auth.authMethod === "none" && (
        <InputPadder>
          <MessageCard
            outerPadding={1}
            innerPadding={1}
            title={t("openApiAuthModal.noAuthNotice.title")}
            description={t("openApiAuthModal.noAuthNotice.description")}
          />
        </InputPadder>
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

            <InputVertical
              withLabel="auth.scopes"
              title={t("openApiAuthModal.scopes.title")}
              suffix="optional"
              subDescription={t("openApiAuthModal.scopes.description")}
            >
              <InputTypeInField
                name="auth.scopes"
                placeholder={t("openApiAuthModal.scopes.placeholder")}
              />
            </InputVertical>

            <InputHorizontal
              withLabel="auth.supportsPkce"
              title={t("openApiAuthModal.pkce.label")}
              description={t("openApiAuthModal.pkce.description")}
            >
              <InputSwitchField name="auth.supportsPkce" />
            </InputHorizontal>

            <OAuthConnectionCheck
              values={auth}
              configId={oauthConfigId}
              disabled={disabled || Boolean(authErrors)}
            />

            <InputVertical
              withLabel="oauth-redirect-uri"
              title={t("openApiAuthModal.redirectUri.title")}
              subDescription={t("openApiAuthModal.redirectUri.description")}
            >
              <InputTypeIn
                id="oauth-redirect-uri"
                variant="readOnly"
                font="main-ui-mono"
                value={redirectUri}
                rightChildren={
                  <CopyButton
                    getCopyText={() => redirectUri}
                    tooltip={t("openApiAuthModal.redirectUri.copyTooltip")}
                    prominence="tertiary"
                    size="sm"
                  />
                }
              />
            </InputVertical>
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
        <InputPadder>
          <MessageCard
            outerPadding={1}
            innerPadding={1}
            title={t("openApiAuthModal.passThroughNotice.title")}
            description={t("openApiAuthModal.passThroughNotice.description", {
              appName,
            })}
          />
        </InputPadder>
      )}
    </fieldset>
  );
}
