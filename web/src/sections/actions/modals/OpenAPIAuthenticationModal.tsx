"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Formik, Form, FormikHelpers } from "formik";
import * as Yup from "yup";
import { Modal } from "@opal/components";
import {
  Button,
  Divider,
  MessageCard,
  InputPasswordTypeIn,
  InputSwitch,
} from "@opal/components";
import { InputSingleSelect } from "@opal/components";
import { InputTypeIn } from "@opal/components";
import { FormField } from "@/refresh-components/form/FormField";
import Text from "@/refresh-components/texts/Text";
import { CopyButton } from "@opal/components";
import {
  InputKeyValue as KeyValueInput,
  type KeyValue,
} from "@opal/components";
import { OAuthConfig } from "@/lib/tools/types";
import { getOAuthConfig } from "@/lib/oauth/api";
import {
  MASKED_OAUTH_CREDENTIAL,
  type OAuthConfigFields,
} from "@/lib/oauth/config";
import OAuthPKCESupport from "@/sections/actions/oauth/OAuthPKCESupport";
import OAuthConnectionCheck from "@/sections/actions/oauth/OAuthConnectionCheck";
import { SvgArrowExchange } from "@opal/icons";
import { useOAuthPassThroughEnabled } from "@/lib/auth/hooks";
import { useSettings } from "@/lib/settings/hooks";

export type AuthMethod = "oauth" | "custom-header" | "pt-oauth";

export interface OpenAPIAuthFormValues extends OAuthConfigFields {
  authMethod: AuthMethod;
  headers: KeyValue[];
}

interface OpenAPIAuthenticationModalProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  skipOverlay?: boolean;
  defaultMethod?: AuthMethod;
  oauthConfigId?: number | null;
  initialHeaders?: KeyValue[] | null;
  onConnect?: (values: OpenAPIAuthFormValues) => Promise<void> | void;
  onSkip?: () => void;
  entityName?: string | null;
  passthroughOAuthEnabled?: boolean;
}

const defaultValues: OpenAPIAuthFormValues = {
  authMethod: "oauth",
  authorizationUrl: "",
  tokenUrl: "",
  clientId: "",
  clientSecret: "",
  scopes: "",
  supportsPkce: false,
  headers: [
    {
      key: "Authorization",
      value: "",
    },
  ],
};

export default function OpenAPIAuthenticationModal({
  isOpen,
  onClose,
  title,
  description,
  skipOverlay = false,
  defaultMethod = "oauth",
  oauthConfigId = null,
  initialHeaders = null,
  passthroughOAuthEnabled = false,
  onConnect,
  onSkip,
  entityName = null,
}: OpenAPIAuthenticationModalProps) {
  const t = useTranslations("actions");
  const { appName } = useSettings();
  const isOAuthEnabled = useOAuthPassThroughEnabled();
  const [existingOAuthConfig, setExistingOAuthConfig] =
    useState<OAuthConfig | null>(null);
  const [isLoadingOAuthConfig, setIsLoadingOAuthConfig] = useState(false);
  const [oauthConfigError, setOAuthConfigError] = useState<string | null>(null);

  const isEditingOAuthConfig = Boolean(oauthConfigId);
  const hasInitialHeaders =
    Array.isArray(initialHeaders) && initialHeaders.length > 0;
  const isEditMode = isEditingOAuthConfig || hasInitialHeaders;
  const shouldDisableForm =
    isEditingOAuthConfig &&
    isLoadingOAuthConfig &&
    !existingOAuthConfig &&
    !oauthConfigError;

  const redirectUri = useMemo(() => {
    if (typeof window === "undefined") {
      return "https://{YOUR_DOMAIN}/oauth-config/callback";
    }
    return `${window.location.origin}/oauth-config/callback`;
  }, []);

  useEffect(() => {
    let isActive = true;

    if (!isOpen || !oauthConfigId) {
      setExistingOAuthConfig(null);
      setOAuthConfigError(null);
      setIsLoadingOAuthConfig(false);
      return () => {
        isActive = false;
      };
    }

    const fetchConfig = async () => {
      setIsLoadingOAuthConfig(true);
      setOAuthConfigError(null);
      try {
        const config = await getOAuthConfig(oauthConfigId);
        if (!isActive) {
          return;
        }
        setExistingOAuthConfig(config);
      } catch (error) {
        console.error("Failed to load OAuth configuration", error);
        if (isActive) {
          setExistingOAuthConfig(null);
          setOAuthConfigError(t("openApiAuthModal.errors.loadConfigFailed"));
        }
      } finally {
        if (isActive) {
          setIsLoadingOAuthConfig(false);
        }
      }
    };

    fetchConfig();

    return () => {
      isActive = false;
    };
  }, [isOpen, oauthConfigId, t]);

  const dynamicValidationSchema = useMemo(
    () =>
      Yup.object({
        authMethod: Yup.mixed<AuthMethod>()
          .oneOf(["oauth", "pt-oauth", "custom-header"])
          .required(t("openApiAuthModal.authMethod.required")),
        authorizationUrl: Yup.string()
          .url(t("openApiAuthModal.errors.invalidUrl"))
          .when("authMethod", {
            is: "oauth",
            then: (schema) =>
              schema.required(t("openApiAuthModal.authorizationUrl.required")),
            otherwise: (schema) => schema.notRequired(),
          }),
        tokenUrl: Yup.string()
          .url(t("openApiAuthModal.errors.invalidUrl"))
          .when("authMethod", {
            is: "oauth",
            then: (schema) =>
              schema.required(t("openApiAuthModal.tokenUrl.required")),
            otherwise: (schema) => schema.notRequired(),
          }),
        clientId: Yup.string().when("authMethod", {
          is: "oauth",
          then: (schema) =>
            isEditingOAuthConfig
              ? schema.optional()
              : schema.required(t("openApiAuthModal.clientId.required")),
          otherwise: (schema) => schema.notRequired(),
        }),
        clientSecret: Yup.string().when("authMethod", {
          is: "oauth",
          then: (schema) =>
            isEditingOAuthConfig
              ? schema.optional()
              : schema.required(t("openApiAuthModal.clientSecret.required")),
          otherwise: (schema) => schema.notRequired(),
        }),
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
              Yup.object({
                key: Yup.string(),
                value: Yup.string(),
              })
            ),
        }),
      }),
    [isEditingOAuthConfig, t]
  );

  const computedInitialValues = useMemo<OpenAPIAuthFormValues>(() => {
    const baseHeaders =
      hasInitialHeaders && initialHeaders
        ? initialHeaders.map((header) => ({ ...header }))
        : defaultValues.headers.map((header) => ({ ...header }));

    if (isEditingOAuthConfig) {
      const shouldMaskCredentials = Boolean(
        existingOAuthConfig?.has_client_credentials
      );
      return {
        authMethod: "oauth",
        authorizationUrl:
          existingOAuthConfig?.authorization_url ||
          defaultValues.authorizationUrl,
        tokenUrl: existingOAuthConfig?.token_url || defaultValues.tokenUrl,
        clientId: shouldMaskCredentials ? MASKED_OAUTH_CREDENTIAL : "",
        clientSecret: shouldMaskCredentials ? MASKED_OAUTH_CREDENTIAL : "",
        scopes: existingOAuthConfig?.scopes?.join(", ") || "",
        supportsPkce: existingOAuthConfig?.supports_pkce ?? false,
        headers: baseHeaders,
      };
    }

    if (hasInitialHeaders && initialHeaders) {
      return {
        ...defaultValues,
        authMethod: "custom-header",
        headers: baseHeaders,
      };
    }

    if (passthroughOAuthEnabled) {
      return {
        ...defaultValues,
        authMethod: "pt-oauth",
      };
    }

    return {
      ...defaultValues,
      authMethod: defaultMethod,
      headers: baseHeaders,
    };
  }, [
    defaultMethod,
    existingOAuthConfig,
    hasInitialHeaders,
    initialHeaders,
    isEditingOAuthConfig,
    passthroughOAuthEnabled,
  ]);

  const handleSubmit = useCallback(
    async (
      values: OpenAPIAuthFormValues,
      formikHelpers: FormikHelpers<OpenAPIAuthFormValues>
    ) => {
      if (shouldDisableForm) {
        formikHelpers.setSubmitting(false);
        return;
      }
      try {
        await onConnect?.(values);
        onClose();
      } finally {
        formikHelpers.setSubmitting(false);
      }
    },
    [onConnect, onClose, shouldDisableForm]
  );

  const handleSkip = useCallback(() => {
    if (onSkip) {
      onSkip();
    } else {
      onClose();
    }
  }, [onSkip, onClose]);

  return (
    <Modal
      open={isOpen}
      onOpenChange={(open) => {
        if (!open) {
          onClose();
        }
      }}
    >
      <Modal.Content width="sm" height="lg" skipOverlay={skipOverlay}>
        <Modal.Header
          icon={SvgArrowExchange}
          title={title}
          description={description ?? t("openApiAuthModal.header.description")}
          onClose={onClose}
        />

        <Formik
          initialValues={computedInitialValues}
          validationSchema={dynamicValidationSchema}
          validateOnMount
          enableReinitialize
          onSubmit={handleSubmit}
        >
          {({
            values,
            errors,
            touched,
            handleChange,
            setFieldValue,
            setFieldError,
            isSubmitting,
            isValid,
            dirty,
          }) => (
            <Form className="flex flex-col h-full">
              <Modal.Body>
                {oauthConfigError && (
                  <div className="mb-3">
                    <Text
                      as="p"
                      mainUiBody
                      className="text-action-text-danger-05"
                    >
                      {oauthConfigError}
                    </Text>
                  </div>
                )}

                {shouldDisableForm ? (
                  <div className="flex min-h-[220px] items-center justify-center rounded-12 border border-border-01 bg-background-tint-00">
                    <Text as="p" secondaryBody text03>
                      {t("openApiAuthModal.loading.label")}
                    </Text>
                  </div>
                ) : (
                  <>
                    <div className="flex flex-col gap-4 px-2 pt-2">
                      <FormField
                        name="authMethod"
                        state={
                          errors.authMethod && touched.authMethod
                            ? "error"
                            : touched.authMethod
                              ? "success"
                              : "idle"
                        }
                      >
                        <FormField.Label>
                          {t("openApiAuthModal.authMethod.label")}
                        </FormField.Label>
                        <FormField.Control asChild>
                          <InputSingleSelect
                            value={values.authMethod}
                            onValueChange={(value) =>
                              setFieldValue("authMethod", value)
                            }
                            defaultOption="oauth"
                            placeholder={t(
                              "openApiAuthModal.authMethod.placeholder"
                            )}
                            options={[
                              {
                                value: "oauth",
                                title: t(
                                  "openApiAuthModal.authMethod.oauth.label"
                                ),
                                description: t(
                                  "openApiAuthModal.authMethod.oauth.description"
                                ),
                              },
                              ...(isOAuthEnabled
                                ? [
                                    {
                                      value: "pt-oauth",
                                      title: t(
                                        "openApiAuthModal.authMethod.ptOauth.label"
                                      ),
                                      description: t(
                                        "openApiAuthModal.authMethod.ptOauth.description",
                                        { appName }
                                      ),
                                    },
                                  ]
                                : []),
                              {
                                value: "custom-header",
                                title: t(
                                  "openApiAuthModal.authMethod.customHeader.label"
                                ),
                                description: t(
                                  "openApiAuthModal.authMethod.customHeader.description"
                                ),
                              },
                            ]}
                          />
                        </FormField.Control>
                        <FormField.Message
                          messages={{
                            error: errors.authMethod,
                          }}
                        />
                      </FormField>
                    </div>

                    <Divider paddingPerpendicular={0} />

                    {values.authMethod === "oauth" && (
                      <section className="flex flex-col gap-4 rounded-12 bg-background-tint-00 border border-border-01 p-4">
                        <FormField
                          name="authorizationUrl"
                          state={
                            errors.authorizationUrl && touched.authorizationUrl
                              ? "error"
                              : touched.authorizationUrl
                                ? "success"
                                : "idle"
                          }
                        >
                          <FormField.Label>
                            {t("openApiAuthModal.authorizationUrl.label")}
                          </FormField.Label>
                          <FormField.Control asChild>
                            <InputTypeIn
                              name="authorizationUrl"
                              value={values.authorizationUrl}
                              onChange={handleChange}
                              placeholder={t(
                                "placeholders.oauthAuthorizationUrl"
                              )}
                            />
                          </FormField.Control>
                          <FormField.Message
                            messages={{
                              error: errors.authorizationUrl,
                            }}
                          />
                        </FormField>

                        <FormField
                          name="tokenUrl"
                          state={
                            errors.tokenUrl && touched.tokenUrl
                              ? "error"
                              : touched.tokenUrl
                                ? "success"
                                : "idle"
                          }
                        >
                          <FormField.Label>
                            {t("openApiAuthModal.tokenUrl.label")}
                          </FormField.Label>
                          <FormField.Control asChild>
                            <InputTypeIn
                              name="tokenUrl"
                              value={values.tokenUrl}
                              onChange={handleChange}
                              placeholder={t("placeholders.oauthTokenUrl")}
                            />
                          </FormField.Control>
                          <FormField.Message
                            messages={{
                              error: errors.tokenUrl,
                            }}
                          />
                        </FormField>

                        <OAuthPKCESupport
                          authorizationUrl={values.authorizationUrl}
                          tokenUrl={values.tokenUrl}
                        />

                        <FormField
                          name="clientId"
                          state={
                            errors.clientId && touched.clientId
                              ? "error"
                              : touched.clientId
                                ? "success"
                                : "idle"
                          }
                        >
                          <FormField.Label>
                            {t("openApiAuthModal.clientId.label")}
                          </FormField.Label>
                          <FormField.Control asChild>
                            <InputTypeIn
                              name="clientId"
                              value={values.clientId}
                              onChange={handleChange}
                              placeholder=" "
                            />
                          </FormField.Control>
                          {isEditingOAuthConfig && (
                            <FormField.Description>
                              {t("openApiAuthModal.clientId.description")}
                            </FormField.Description>
                          )}
                          <FormField.Message
                            messages={{
                              error: errors.clientId,
                            }}
                          />
                        </FormField>

                        <FormField
                          name="clientSecret"
                          state={
                            errors.clientSecret && touched.clientSecret
                              ? "error"
                              : touched.clientSecret
                                ? "success"
                                : "idle"
                          }
                        >
                          <FormField.Label>
                            {t("openApiAuthModal.clientSecret.label")}
                          </FormField.Label>
                          <FormField.Control asChild>
                            <InputPasswordTypeIn
                              name="clientSecret"
                              value={values.clientSecret}
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
                            messages={{
                              error: errors.clientSecret,
                            }}
                          />
                        </FormField>

                        <FormField
                          name="scopes"
                          state={
                            errors.scopes && touched.scopes
                              ? "error"
                              : touched.scopes
                                ? "success"
                                : "idle"
                          }
                        >
                          <FormField.Label>
                            {t.rich("openApiAuthModal.scopes.label", {
                              optional: (chunks) => (
                                <span className="text-text-03">{chunks}</span>
                              ),
                            })}
                          </FormField.Label>
                          <FormField.Control asChild>
                            <InputTypeIn
                              name="scopes"
                              value={values.scopes}
                              onChange={handleChange}
                              placeholder={t(
                                "openApiAuthModal.scopes.placeholder"
                              )}
                            />
                          </FormField.Control>
                          <FormField.Description>
                            {t("openApiAuthModal.scopes.description")}
                          </FormField.Description>
                          <FormField.Message
                            messages={{
                              error: errors.scopes,
                            }}
                          />
                        </FormField>

                        <FormField name="supportsPkce">
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
                                checked={values.supportsPkce}
                                onCheckedChange={(checked) =>
                                  setFieldValue("supportsPkce", checked)
                                }
                              />
                            </FormField.Control>
                          </div>
                        </FormField>

                        <OAuthConnectionCheck
                          values={values}
                          configId={oauthConfigId}
                          disabled={!isValid || isSubmitting}
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
                                  <span className="font-secondary-action">
                                    {chunks}
                                  </span>
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
                                tooltip={t(
                                  "openApiAuthModal.redirectUri.copyTooltip"
                                )}
                                prominence="tertiary"
                                size="sm"
                              />
                            </div>
                          </div>
                        </div>
                      </section>
                    )}
                    {values.authMethod === "custom-header" && (
                      <section className="flex flex-col gap-4 rounded-12 bg-background-tint-00 border border-border-01 p-4">
                        <div className="flex flex-col gap-2">
                          <Text as="p" mainUiAction text04>
                            {t("openApiAuthModal.headers.title")}
                          </Text>
                          <Text as="p" secondaryBody text03>
                            {t("openApiAuthModal.headers.description")}
                          </Text>
                        </div>
                        <FormField
                          name="headers"
                          state={errors.headers ? "error" : "idle"}
                        >
                          <FormField.Control asChild>
                            <KeyValueInput
                              keyTitle={t("openApiAuthModal.headers.keyTitle")}
                              valueTitle={t(
                                "openApiAuthModal.headers.valueTitle"
                              )}
                              items={values.headers}
                              onChange={(items) =>
                                setFieldValue("headers", items)
                              }
                              addButtonLabel={t(
                                "openApiAuthModal.headers.addButton.label"
                              )}
                              onValidationError={(message) =>
                                setFieldError("headers", message || undefined)
                              }
                              layout="equal"
                            />
                          </FormField.Control>
                          <FormField.Message
                            messages={{
                              error:
                                typeof errors.headers === "string"
                                  ? errors.headers
                                  : undefined,
                            }}
                          />
                        </FormField>
                      </section>
                    )}
                    {values.authMethod === "pt-oauth" && (
                      <MessageCard
                        outerPadding={1}
                        innerPadding={1}
                        title={t("openApiAuthModal.passThroughNotice.title")}
                        description={t(
                          "openApiAuthModal.passThroughNotice.description",
                          { appName }
                        )}
                      />
                    )}
                  </>
                )}
              </Modal.Body>

              <Modal.Footer>
                <Button
                  prominence="tertiary"
                  type="button"
                  onClick={handleSkip}
                >
                  {t("openApiAuthModal.cancelButton.label")}
                </Button>
                <Button
                  disabled={
                    !isValid || isSubmitting || shouldDisableForm || !dirty
                  }
                  type="submit"
                >
                  {isSubmitting
                    ? t("openApiAuthModal.submitButton.pendingLabel")
                    : t("openApiAuthModal.submitButton.label")}
                </Button>
              </Modal.Footer>
            </Form>
          )}
        </Formik>
      </Modal.Content>
    </Modal>
  );
}
