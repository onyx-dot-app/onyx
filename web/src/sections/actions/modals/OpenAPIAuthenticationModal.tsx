"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Formik, Form, FormikHelpers } from "formik";
import * as Yup from "yup";
import Modal from "@/refresh-components/Modal";
import { Button, Divider, MessageCard } from "@opal/components";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import { InputTypeIn } from "@opal/components";
import PasswordInputTypeIn from "@/refresh-components/inputs/PasswordInputTypeIn";
import { FormField } from "@/refresh-components/form/FormField";
import Text from "@/refresh-components/texts/Text";
import { CopyButton } from "@opal/components";
import KeyValueInput, {
  KeyValue,
} from "@/refresh-components/inputs/InputKeyValue";
import { OAuthConfig } from "@/lib/tools/interfaces";
import { getOAuthConfig } from "@/lib/oauth/api";
import { SvgArrowExchange } from "@opal/icons";
import { useAuthType } from "@/lib/hooks";
import { AuthType } from "@/lib/constants";

export type AuthMethod = "oauth" | "custom-header" | "pt-oauth";

export interface OpenAPIAuthFormValues {
  authMethod: AuthMethod;
  authorizationUrl: string;
  tokenUrl: string;
  clientId: string;
  clientSecret: string;
  scopes: string;
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

const MASKED_CREDENTIAL_VALUE = "********";

const defaultValues: OpenAPIAuthFormValues = {
  authMethod: "oauth",
  authorizationUrl: "",
  tokenUrl: "",
  clientId: "",
  clientSecret: "",
  scopes: "",
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
  description = "完成连接认证后即可开始使用 OpenAPI 动作。",
  skipOverlay = false,
  defaultMethod = "oauth",
  oauthConfigId = null,
  initialHeaders = null,
  passthroughOAuthEnabled = false,
  onConnect,
  onSkip,
  entityName = null,
}: OpenAPIAuthenticationModalProps) {
  const authType = useAuthType();
  const isOAuthEnabled =
    authType === AuthType.OIDC || authType === AuthType.GOOGLE_OAUTH;
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
          setOAuthConfigError(
            "加载现有 OAuth 配置失败。请重新输入详情以更新配置。"
          );
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
  }, [isOpen, oauthConfigId]);

  const dynamicValidationSchema = useMemo(
    () =>
      Yup.object({
        authMethod: Yup.mixed<AuthMethod>()
          .oneOf(["oauth", "pt-oauth", "custom-header"])
          .required("请选择认证方式"),
        authorizationUrl: Yup.string()
          .url("请输入有效 URL")
          .when("authMethod", {
            is: "oauth",
            then: (schema) => schema.required("请输入授权 URL"),
            otherwise: (schema) => schema.notRequired(),
          }),
        tokenUrl: Yup.string()
          .url("请输入有效 URL")
          .when("authMethod", {
            is: "oauth",
            then: (schema) => schema.required("请输入 Token URL"),
            otherwise: (schema) => schema.notRequired(),
          }),
        clientId: Yup.string().when("authMethod", {
          is: "oauth",
          then: (schema) =>
            isEditingOAuthConfig
              ? schema.optional()
              : schema.required("请输入 Client ID"),
          otherwise: (schema) => schema.notRequired(),
        }),
        clientSecret: Yup.string().when("authMethod", {
          is: "oauth",
          then: (schema) =>
            isEditingOAuthConfig
              ? schema.optional()
              : schema.required("请输入 Client Secret"),
          otherwise: (schema) => schema.notRequired(),
        }),
        scopes: Yup.string().notRequired(),
        headers: Yup.array().when("authMethod", {
          is: "custom-header",
          then: () =>
            Yup.array()
              .of(
                Yup.object({
                  key: Yup.string().required("请输入 Header 名称"),
                  value: Yup.string().required("请输入 Header 值"),
                })
              )
              .min(1, "请至少添加一个认证 Header"),
          otherwise: () =>
            Yup.array().of(
              Yup.object({
                key: Yup.string(),
                value: Yup.string(),
              })
            ),
        }),
      }),
    [isEditingOAuthConfig]
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
        clientId: shouldMaskCredentials ? MASKED_CREDENTIAL_VALUE : "",
        clientSecret: shouldMaskCredentials ? MASKED_CREDENTIAL_VALUE : "",
        scopes: existingOAuthConfig?.scopes?.join(", ") || "",
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
      const sanitizeCredentials = (
        formValues: OpenAPIAuthFormValues
      ): OpenAPIAuthFormValues => {
        if (!isEditingOAuthConfig || formValues.authMethod !== "oauth") {
          return formValues;
        }

        const sanitizeValue = (value: string) =>
          value === MASKED_CREDENTIAL_VALUE ? "" : value;

        return {
          ...formValues,
          clientId: sanitizeValue(formValues.clientId),
          clientSecret: sanitizeValue(formValues.clientSecret),
        };
      };

      try {
        const sanitizedValues = sanitizeCredentials(values);
        await onConnect?.(sanitizedValues);
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
          description={description}
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
                      正在加载现有配置...
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
                        <FormField.Label>认证方式</FormField.Label>
                        <FormField.Control asChild>
                          <InputSelect
                            value={values.authMethod}
                            onValueChange={(value) =>
                              setFieldValue("authMethod", value)
                            }
                          >
                            <InputSelect.Trigger placeholder="选择方式" />
                            <InputSelect.Content>
                              <InputSelect.Item
                                value="oauth"
                                description="每位用户都使用自己的凭据通过 OAuth 认证。"
                              >
                                OAuth
                              </InputSelect.Item>
                              {isOAuthEnabled && (
                                <InputSelect.Item
                                  value="pt-oauth"
                                  description="转发用户用于认证 Glomi AI 的 OAuth 访问令牌。"
                                >
                                  OAuth 透传
                                </InputSelect.Item>
                              )}
                              <InputSelect.Item
                                value="custom-header"
                                description="每次请求都发送自定义 Header。"
                              >
                                自定义认证 Header
                              </InputSelect.Item>
                            </InputSelect.Content>
                          </InputSelect>
                        </FormField.Control>
                        <FormField.Message
                          messages={{
                            error: errors.authMethod,
                          }}
                        />
                      </FormField>
                    </div>

                    <Divider paddingPerpendicular="fit" />

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
                          <FormField.Label>授权 URL</FormField.Label>
                          <FormField.Control asChild>
                            <InputTypeIn
                              name="authorizationUrl"
                              value={values.authorizationUrl}
                              onChange={handleChange}
                              placeholder="https://example.com/oauth/authorize"
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
                          <FormField.Label>Token URL</FormField.Label>
                          <FormField.Control asChild>
                            <InputTypeIn
                              name="tokenUrl"
                              value={values.tokenUrl}
                              onChange={handleChange}
                              placeholder="https://example.com/oauth/access_token"
                            />
                          </FormField.Control>
                          <FormField.Message
                            messages={{
                              error: errors.tokenUrl,
                            }}
                          />
                        </FormField>

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
                          <FormField.Label>OAuth Client ID</FormField.Label>
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
                              留空则保留当前 Client ID。
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
                          <FormField.Label>OAuth Client Secret</FormField.Label>
                          <FormField.Control asChild>
                            <PasswordInputTypeIn
                              name="clientSecret"
                              value={values.clientSecret}
                              onChange={handleChange}
                              placeholder=" "
                            />
                          </FormField.Control>
                          {isEditingOAuthConfig && (
                            <FormField.Description>
                              留空则保留当前 Client Secret。
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
                            Scopes{" "}
                            <span className="text-text-03">（可选）</span>
                          </FormField.Label>
                          <FormField.Control asChild>
                            <InputTypeIn
                              name="scopes"
                              value={values.scopes}
                              onChange={handleChange}
                              placeholder="例如 repo, user"
                            />
                          </FormField.Control>
                          <FormField.Description>
                            要请求的 OAuth scope 列表，用英文逗号分隔。
                          </FormField.Description>
                          <FormField.Message
                            messages={{
                              error: errors.scopes,
                            }}
                          />
                        </FormField>

                        <div className="flex flex-col gap-3 rounded-12 bg-background-tint-01 p-3">
                          <Text as="p" text03 secondaryBody>
                            只有启用 OIDC 或 OAuth 认证后，才能使用 OAuth 透传。
                          </Text>
                          <div className="flex flex-col gap-2 w-full">
                            <Text
                              as="p"
                              text03
                              secondaryBody
                              className="flex flex-wrap gap-1"
                            >
                              使用{" "}
                              <span className="font-secondary-action">
                                redirect URI
                              </span>
                              :
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
                                tooltip="复制 redirect URI"
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
                            认证 Header
                          </Text>
                          <Text as="p" secondaryBody text03>
                            为发送到此动作 API 端点的所有请求指定自定义 Header。
                          </Text>
                        </div>
                        <FormField
                          name="headers"
                          state={errors.headers ? "error" : "idle"}
                        >
                          <FormField.Control asChild>
                            <KeyValueInput
                              keyTitle="Header 名称"
                              valueTitle="值"
                              items={values.headers}
                              onChange={(items) =>
                                setFieldValue("headers", items)
                              }
                              addButtonLabel="添加 Header"
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
                        title="对共享身份提供商的服务使用透传认证"
                        description="Glomi AI 会把用户的 OAuth 访问令牌作为 Authorization 请求头直接转发给服务端。请确认该服务端支持同一身份提供商的认证。"
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
                  取消
                </Button>
                <Button
                  disabled={
                    !isValid || isSubmitting || shouldDisableForm || !dirty
                  }
                  type="submit"
                >
                  {isSubmitting ? "正在连接..." : "连接"}
                </Button>
              </Modal.Footer>
            </Form>
          )}
        </Formik>
      </Modal.Content>
    </Modal>
  );
}
