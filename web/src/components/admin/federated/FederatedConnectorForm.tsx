"use client";

import { useState, useEffect } from "react";
import Button from "@/refresh-components/buttons/Button";
import { Button as OpalButton, Divider } from "@opal/components";
import {
  ConfigurableSources,
  CredentialFieldSpec,
  ConfigurationFieldSpec,
  FederatedConnectorCreateRequest,
  FederatedConnectorDetail,
  CredentialSchemaResponse,
} from "@/lib/types";
import { getSourceMetadata } from "@/lib/sources";
import { SourceIcon } from "@/components/SourceIcon";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useRouter } from "next/navigation";
import Text from "@/refresh-components/texts/Text";
import { AlertTriangle, Check, Loader2, Trash2Icon, Info } from "lucide-react";
import BackButton from "@/refresh-components/buttons/BackButton";
import Title from "@/components/ui/title";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { DropdownMenuItemWithTooltip } from "@/components/ui/dropdown-menu-with-tooltip";
import { toast } from "@/hooks/useToast";

import { Badge } from "@/components/ui/badge";
import { Tooltip } from "@opal/components";
import { ListFieldInput } from "@/refresh-components/inputs/ListFieldInput";
import { Checkbox } from "@opal/components";
import { SvgSettings, SvgSimpleLoader } from "@opal/icons";

export interface FederatedConnectorFormProps {
  connector: ConfigurableSources;
  connectorId?: number; // Optional ID for editing existing connector
  preloadedConnectorData?: FederatedConnectorDetail;
  preloadedCredentialSchema?: CredentialSchemaResponse;
}

interface CredentialForm {
  [key: string]: string;
}

interface ConfigForm {
  [key: string]: string | boolean | string[] | number | undefined;
}

interface FormState {
  credentials: CredentialForm;
  config: ConfigForm;
  schema: Record<string, CredentialFieldSpec> | null;
  configurationSchema: Record<string, ConfigurationFieldSpec> | null;
  schemaError: string | null;
  configurationSchemaError: string | null;
  connectorError: string | null;
}

async function validateCredentials(
  source: string,
  credentials: CredentialForm
): Promise<{ success: boolean; message: string }> {
  try {
    const response = await fetch(
      `/api/federated/sources/federated_${source}/credentials/validate`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(credentials),
      }
    );

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      return {
        success: false,
        message:
          errorData.detail || `校验失败：${response.statusText}`,
      };
    }

    const result = await response.json();
    return {
      success: result,
      message: result ? "凭据有效" : "凭据无效",
    };
  } catch (error) {
    return { success: false, message: `校验错误：${error}` };
  }
}

async function createFederatedConnector(
  source: string,
  credentials: CredentialForm,
  config?: ConfigForm
): Promise<{ success: boolean; message: string }> {
  try {
    const response = await fetch("/api/federated", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        source: `federated_${source}`,
        credentials,
        config: config || {},
      } as FederatedConnectorCreateRequest),
    });

    if (response.ok) {
      return {
        success: true,
        message: "联邦连接器创建成功！",
      };
    } else {
      const errorData = await response.json();
      return {
        success: false,
        message: errorData.detail || "创建联邦连接器失败",
      };
    }
  } catch (error) {
    return { success: false, message: `Error: ${error}` };
  }
}

async function updateFederatedConnector(
  id: number,
  credentials: CredentialForm | null,
  config?: ConfigForm
): Promise<{ success: boolean; message: string }> {
  try {
    const response = await fetch(`/api/federated/${id}`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        credentials: credentials ?? undefined,
        config: config || {},
      }),
    });

    if (response.ok) {
      return {
        success: true,
        message: "联邦连接器更新成功！",
      };
    } else {
      const errorData = await response.json();
      return {
        success: false,
        message: errorData.detail || "更新联邦连接器失败",
      };
    }
  } catch (error) {
    return { success: false, message: `Error: ${error}` };
  }
}

async function deleteFederatedConnector(
  id: number
): Promise<{ success: boolean; message: string }> {
  try {
    const response = await fetch(`/api/federated/${id}`, {
      method: "DELETE",
    });

    if (response.ok) {
      return {
        success: true,
        message: "联邦连接器已删除！",
      };
    } else {
      const errorData = await response.json();
      return {
        success: false,
        message: errorData.detail || "删除联邦连接器失败",
      };
    }
  } catch (error) {
    return { success: false, message: `Error: ${error}` };
  }
}

export function FederatedConnectorForm({
  connector,
  connectorId,
  preloadedConnectorData,
  preloadedCredentialSchema,
}: FederatedConnectorFormProps) {
  const router = useRouter();
  const sourceMetadata = getSourceMetadata(connector);
  const isEditMode = connectorId !== undefined;

  const [formState, setFormState] = useState<FormState>({
    // In edit mode, don't populate credentials with masked values from the API.
    // Masked values (e.g. "••••••••••••") would be saved back and corrupt the real credentials.
    credentials: isEditMode ? {} : preloadedConnectorData?.credentials || {},
    config: preloadedConnectorData?.config || {},
    schema: preloadedCredentialSchema?.credentials || null,
    configurationSchema: null,
    schemaError: null,
    configurationSchemaError: null,
    connectorError: null,
  });
  const [credentialsModified, setCredentialsModified] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitMessage, setSubmitMessage] = useState<string | null>(null);
  const [submitSuccess, setSubmitSuccess] = useState<boolean | null>(null);
  const [isValidating, setIsValidating] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [isLoadingSchema, setIsLoadingSchema] = useState(
    !preloadedCredentialSchema
  );
  const [configValidationErrors, setConfigValidationErrors] = useState<
    Record<string, string>
  >({});

  // Fetch credential schema if not preloaded
  useEffect(() => {
    const fetchCredentialSchema = async () => {
      if (!preloadedCredentialSchema) {
        setIsLoadingSchema(true);
        try {
          const response = await fetch(
            `/api/federated/sources/federated_${connector}/credentials/schema`
          );

          if (!response.ok) {
            throw new Error(
              `获取凭据 schema 失败：${response.statusText}`
            );
          }

          const responseData = await response.json();
          setFormState((prev) => ({
            ...prev,
            schema: responseData.credentials,
            schemaError: null,
          }));
        } catch (error) {
          console.error("获取凭据 schema 出错：", error);
          setFormState((prev) => ({
            ...prev,
            schemaError: `加载凭据 schema 失败：${error}`,
          }));
        } finally {
          setIsLoadingSchema(false);
        }
      }
    };

    fetchCredentialSchema();
  }, [connector, preloadedCredentialSchema]);

  // Fetch configuration schema for connector configuration
  useEffect(() => {
    const fetchConfigurationSchema = async () => {
      try {
        const response = await fetch(
          `/api/federated/sources/federated_${connector}/configuration/schema`
        );

        if (!response.ok) {
          throw new Error(
            `获取配置 schema 失败：${response.statusText}`
          );
        }

        const responseData = await response.json();
        const configurationSchema = responseData.configuration;

        // Initialize config with defaults - merge with existing config
        // This ensures boolean fields like search_all_channels have explicit values for UI state
        if (configurationSchema) {
          const configWithDefaults: Record<string, any> = {};
          (Object.entries(configurationSchema) as [string, any][]).forEach(
            ([key, field]) => {
              if (field.default !== undefined) {
                configWithDefaults[key] = field.default;
              }
            }
          );

          setFormState((prev) => ({
            ...prev,
            // Merge defaults first, then overlay saved config values
            config: { ...configWithDefaults, ...prev.config },
            configurationSchema,
            configurationSchemaError: null,
          }));
        } else {
          setFormState((prev) => ({
            ...prev,
            configurationSchema,
            configurationSchemaError: null,
          }));
        }
      } catch (error) {
        console.error("获取配置 schema 出错：", error);
        setFormState((prev) => ({
          ...prev,
          configurationSchemaError: `加载配置 schema 失败：${error}`,
        }));
      }
    };

    fetchConfigurationSchema();
  }, [connector, isEditMode]);

  // Show loading state at the top level if schema is loading
  if (isLoadingSchema) {
    return (
      <div className="mx-auto w-[800px]">
        <div className="flex flex-col items-center justify-center py-16">
          <Loader2 className="h-8 w-8 animate-spin text-blue-500 mb-4" />
          <div className="text-center">
            <p className="text-lg font-medium text-gray-700 mb-2">
              正在加载凭据 schema...
            </p>
            <p className="text-sm text-gray-500">
              正在获取此连接器类型所需字段
            </p>
          </div>
        </div>
      </div>
    );
  }

  const handleCredentialChange = (key: string, value: string) => {
    setCredentialsModified(true);
    setFormState((prev) => ({
      ...prev,
      credentials: {
        ...prev.credentials,
        [key]: value,
      },
    }));
  };

  const handleConfigChange = (key: string, value: any) => {
    setFormState((prev) => ({
      ...prev,
      config: {
        ...prev.config,
        [key]: value,
      },
    }));
  };

  const handleValidateCredentials = async () => {
    if (!formState.schema) return;
    if (isEditMode && !credentialsModified) {
      setSubmitMessage("校验前请输入新的凭据值。");
      setSubmitSuccess(false);
      return;
    }

    setIsValidating(true);
    setSubmitMessage(null);
    setSubmitSuccess(null);

    try {
      const result = await validateCredentials(
        connector,
        formState.credentials
      );
      setSubmitMessage(result.message);
      setSubmitSuccess(result.success);
    } catch (error) {
      setSubmitMessage(`校验错误：${error}`);
      setSubmitSuccess(false);
    } finally {
      setIsValidating(false);
    }
  };

  const handleDeleteConnector = async () => {
    if (!connectorId) return;

    const confirmed = window.confirm(
      "确定要删除此联邦连接器吗？此操作无法撤销。"
    );

    if (!confirmed) return;

    setIsDeleting(true);

    try {
      const result = await deleteFederatedConnector(connectorId);

      if (result.success) {
        toast.success(result.message);
        // Redirect after a short delay
        setTimeout(() => {
          router.push("/admin/indexing/status");
        }, 500);
      } else {
        toast.error(result.message);
      }
    } catch (error) {
      toast.error(`删除连接器出错：${error}`);
    } finally {
      setIsDeleting(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    setSubmitMessage(null);
    setSubmitSuccess(null);

    try {
      const shouldValidateCredentials = !isEditMode || credentialsModified;

      // Validate required fields (skip for credentials in edit mode when unchanged)
      if (formState.schema && shouldValidateCredentials) {
        const missingRequired = Object.entries(formState.schema)
          .filter(
            ([key, field]) => field.required && !formState.credentials[key]
          )
          .map(([key]) => key);

        if (missingRequired.length > 0) {
          setSubmitMessage(
            `缺少必填字段：${missingRequired.join(", ")}`
          );
          setSubmitSuccess(false);
          setIsSubmitting(false);
          return;
        }
      }

      // Validate configuration fields (Slack-specific validation)
      const configErrors = getConfigValidationErrors();
      if (Object.keys(configErrors).length > 0) {
        setConfigValidationErrors(configErrors);
        // Show the first error message
        const firstError = Object.values(configErrors)[0] as string;
        setSubmitMessage(firstError);
        setSubmitSuccess(false);
        setIsSubmitting(false);
        return;
      }
      setConfigValidationErrors({});

      // Validate credentials before creating/updating (skip in edit mode when unchanged)
      if (shouldValidateCredentials) {
        const validation = await validateCredentials(
          connector,
          formState.credentials
        );
        if (!validation.success) {
          setSubmitMessage(
            `凭据校验失败：${validation.message}`
          );
          setSubmitSuccess(false);
          setIsSubmitting(false);
          return;
        }
      }

      // Create or update the connector
      const result =
        isEditMode && connectorId
          ? await updateFederatedConnector(
              connectorId,
              credentialsModified ? formState.credentials : null,
              formState.config
            )
          : await createFederatedConnector(
              connector,
              formState.credentials,
              formState.config
            );

      setSubmitMessage(result.message);
      setSubmitSuccess(result.success);
      setIsSubmitting(false);

      if (result.success) {
        // Redirect after a short delay
        setTimeout(() => {
          router.push("/admin/indexing/status");
        }, 500);
      }
    } catch (error) {
      setSubmitMessage(`错误：${error}`);
      setSubmitSuccess(false);
      setIsSubmitting(false);
    }
  };

  const renderCredentialFields = () => {
    if (formState.schemaError) {
      return (
        <div className="flex items-center gap-2 p-3 rounded-md bg-red-50 text-red-700 border border-red-200">
          <AlertTriangle size={16} />
          <span className="text-sm">{formState.schemaError}</span>
        </div>
      );
    }

    if (formState.connectorError) {
      return (
        <div className="flex items-center gap-2 p-3 rounded-md bg-red-50 text-red-700 border border-red-200">
          <AlertTriangle size={16} />
          <span className="text-sm">{formState.connectorError}</span>
        </div>
      );
    }

    if (!formState.schema) {
      return (
        <div className="text-sm text-gray-500">
          此连接器类型没有可用的凭据 schema。
        </div>
      );
    }

    return (
      <>
        {Object.entries(formState.schema).map(([fieldKey, fieldSpec]) => (
          <div
            key={fieldKey}
            className="flex items-center justify-between gap-4 py-2"
          >
            <div className="flex-1">
              <Text as="p" mainUiAction text04 className="mb-1">
                {fieldKey
                  .replace(/_/g, " ")
                  .replace(/\b\w/g, (l) => l.toUpperCase())}
                {fieldSpec.required && (
                  <span className="text-red-500 ml-1">*</span>
                )}
              </Text>
              {fieldSpec.description && (
                <Text as="p" mainUiMuted text03>
                  {fieldSpec.description}
                </Text>
              )}
            </div>
            <Input
              id={fieldKey}
              type={fieldSpec.secret ? "password" : "text"}
              placeholder={
                isEditMode && !credentialsModified
                  ? "••••••••（留空以保留当前值）"
                  : fieldSpec.example
                    ? String(fieldSpec.example)
                    : fieldSpec.description
              }
              value={formState.credentials[fieldKey] || ""}
              onChange={(e) => handleCredentialChange(fieldKey, e.target.value)}
              className="w-96"
              required={!isEditMode && fieldSpec.required}
            />
          </div>
        ))}
      </>
    );
  };

  // Helper to determine if channels input should be disabled for Slack
  const disableSlackChannelInput = (fieldKey: string): boolean => {
    if (connector !== "slack" || fieldKey !== "channels") {
      return false;
    }
    // Disable channels field when search_all_channels is true
    return formState.config.search_all_channels === true;
  };

  // Helper to determine if channels field is required for Slack
  const isSlackChannelsRequired = (): boolean => {
    if (connector !== "slack") {
      return false;
    }
    // Channels are required when search_all_channels is false
    return formState.config.search_all_channels === false;
  };

  // Get validation errors for configuration fields (Slack-specific)
  const getConfigValidationErrors = (): Record<string, string> => {
    const errors: Record<string, string> = {};

    if (connector === "slack") {
      // Check if channels are required but not provided
      if (
        formState.config.search_all_channels === false &&
        (!formState.config.channels ||
          !Array.isArray(formState.config.channels) ||
          formState.config.channels.length === 0)
      ) {
        errors.channels =
          "禁用“搜索所有频道”时至少需要一个频道";
      }
    }

    return errors;
  };

  const renderConfigFields = () => {
    if (formState.configurationSchemaError) {
      return (
        <div className="flex items-center gap-2 p-3 rounded-md bg-red-50 text-red-700 border border-red-200">
          <AlertTriangle size={16} />
          <span className="text-sm">{formState.configurationSchemaError}</span>
        </div>
      );
    }

    if (!formState.configurationSchema) {
      return (
        <div className="text-sm text-gray-500">
          此连接器类型没有可用的搜索配置。
        </div>
      );
    }

    const channelInputPlaceholder =
      "输入频道名称或 Regex 模式并按 Enter";

    return (
      <>
        {Object.entries(formState.configurationSchema).map(
          ([fieldKey, fieldSpec]) => {
            const isBoolType = fieldSpec.type === "bool";
            const isListType = fieldSpec.type.startsWith("list[");

            return (
              <div key={fieldKey} className="space-y-2 w-full">
                {isBoolType ? (
                  <div className="flex items-center gap-3 py-2">
                    <Checkbox
                      checked={
                        formState.config[fieldKey] !== undefined
                          ? Boolean(formState.config[fieldKey])
                          : Boolean(fieldSpec.default)
                      }
                      onCheckedChange={(checked) =>
                        handleConfigChange(fieldKey, checked)
                      }
                    />
                    <div className="flex-1">
                      <Text as="p" mainUiAction text04>
                        {fieldKey
                          .replace(/_/g, " ")
                          .replace(/\b\w/g, (l) => l.toUpperCase())}
                      </Text>
                      {fieldSpec.description && (
                        <Text as="p" mainUiMuted text03>
                          {fieldSpec.description}
                        </Text>
                      )}
                    </div>
                  </div>
                ) : (
                  <>
                    {isListType ? (
                      <>
                        <Text as="p" mainUiAction text04>
                          {fieldSpec.description ||
                            fieldKey
                              .replace(/_/g, " ")
                              .replace(/\b\w/g, (l) => l.toUpperCase())}
                          {(fieldSpec.required ||
                            (fieldKey === "channels" &&
                              isSlackChannelsRequired())) && (
                            <span className="text-red-500 ml-1">*</span>
                          )}
                        </Text>
                        <ListFieldInput
                          values={
                            Array.isArray(formState.config[fieldKey])
                              ? (formState.config[fieldKey] as string[])
                              : []
                          }
                          onChange={(values) => {
                            handleConfigChange(fieldKey, values);
                            // Clear validation error when user adds channels
                            if (
                              fieldKey === "channels" &&
                              configValidationErrors.channels
                            ) {
                              setConfigValidationErrors((prev) => {
                                const { channels, ...rest } = prev;
                                return rest;
                              });
                            }
                          }}
                          placeholder={
                            fieldKey === "channels" ||
                            fieldKey === "exclude_channels"
                              ? channelInputPlaceholder
                              : "输入后按 Enter 添加项目"
                          }
                          disabled={disableSlackChannelInput(fieldKey)}
                          error={!!configValidationErrors[fieldKey]}
                        />
                        {configValidationErrors[fieldKey] && (
                          <Text as="p" className="text-red-500 text-sm mt-1">
                            {configValidationErrors[fieldKey]}
                          </Text>
                        )}
                      </>
                    ) : (
                      <div className="flex items-center justify-between gap-4 py-2">
                        <div className="flex-1">
                          <Text as="p" mainUiAction text04 className="mb-1">
                            {fieldKey
                              .replace(/_/g, " ")
                              .replace(/\b\w/g, (l) => l.toUpperCase())}
                            {fieldSpec.required && (
                              <span className="text-red-500 ml-1">*</span>
                            )}
                          </Text>
                          {fieldSpec.description && (
                            <Text as="p" mainUiMuted text03>
                              {fieldSpec.description}
                            </Text>
                          )}
                        </div>
                        <Input
                          id={fieldKey}
                          type={fieldSpec.type === "int" ? "number" : "text"}
                          placeholder={
                            fieldSpec.example
                              ? String(fieldSpec.example)
                              : fieldSpec.description
                          }
                          value={
                            formState.config[fieldKey] !== undefined
                              ? String(formState.config[fieldKey])
                              : ""
                          }
                          onChange={(e) => {
                            const value =
                              fieldSpec.type === "int"
                                ? parseInt(e.target.value, 10)
                                : e.target.value;
                            handleConfigChange(fieldKey, value);
                          }}
                          className="w-96"
                          required={fieldSpec.required}
                        />
                      </div>
                    )}
                  </>
                )}
              </div>
            );
          }
        )}
      </>
    );
  };

  return (
    <div className="mx-auto w-[800px] pb-8">
      <BackButton routerOverride="/admin/indexing/status" />

      <div className="flex items-center justify-between h-16 pb-2 border-b border-neutral-200 dark:border-neutral-600">
        <div className="my-auto">
          <SourceIcon iconSize={32} sourceType={connector} />
        </div>

        <div className="ml-2 overflow-hidden text-ellipsis whitespace-nowrap flex-1 mr-4">
          <div className="text-2xl font-bold text-text-default flex items-center gap-2">
            <span>
              {isEditMode ? "编辑" : "设置"} {sourceMetadata.displayName}
            </span>
            <Badge variant="outline" className="text-xs">
              联邦
            </Badge>
            <Tooltip
              tooltip={
                sourceMetadata.federatedTooltip ||
                "这是联邦连接器。与常规连接器相比，它会带来更高延迟和较低搜索质量。"
              }
              side="bottom"
            >
              <Info className="cursor-help" size={16} />
            </Tooltip>
          </div>
        </div>

        {isEditMode && (
          <div className="ml-auto flex gap-x-2">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <div>
                  <OpalButton prominence="secondary" icon={SvgSettings}>
                    管理
                  </OpalButton>
                </div>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItemWithTooltip
                  onClick={handleDeleteConnector}
                  disabled={isDeleting}
                  className="flex items-center gap-x-2 cursor-pointer px-3 py-2 text-red-600 hover:text-red-700 dark:text-red-400 dark:hover:text-red-300"
                  tooltip={isDeleting ? "正在删除" : undefined}
                >
                  <Trash2Icon className="h-4 w-4" />
                  <span>{isDeleting ? "正在删除..." : "删除"}</span>
                </DropdownMenuItemWithTooltip>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        )}
      </div>

      <Title className="mb-2 mt-6" size="md">
        联邦连接器配置
      </Title>

      <Card className="px-8 py-4">
        <CardContent className="p-0">
          <form onSubmit={handleSubmit}>
            <Text as="p" headingH3>
              凭据
            </Text>
            <Text as="p" mainUiMuted>
              输入此连接器的凭据。
            </Text>
            <div className="space-y-4">{renderCredentialFields()}</div>
            <Divider />
            <Text as="p" headingH3>
              配置
            </Text>
            <div className="space-y-4">{renderConfigFields()}</div>

            <div className="flex gap-2 pt-4 w-full justify-end">
              {submitMessage && (
                <div
                  className={`flex items-center gap-2 p-2 rounded-md ${
                    submitSuccess
                      ? "bg-green-50 text-green-700 border border-green-200"
                      : "bg-red-50 text-red-700 border border-red-200"
                  }`}
                >
                  {submitSuccess ? (
                    <Check size={16} />
                  ) : (
                    <AlertTriangle size={16} />
                  )}
                  <span className="text-sm">{submitMessage}</span>
                </div>
              )}

              {/* TODO(@raunakab): migrate to opal Button once className/iconClassName is resolved */}
              <Button
                type="button"
                secondary
                onClick={handleValidateCredentials}
                disabled={isValidating || !formState.schema}
                className="flex ml-auto"
              >
                {isValidating ? "正在校验..." : "校验"}
              </Button>
              {/* TODO(@raunakab): migrate to opal Button once className/iconClassName is resolved */}
              <Button
                type="submit"
                disabled={isSubmitting || !formState.schema}
                className="flex"
                leftIcon={isSubmitting ? SvgSimpleLoader : undefined}
              >
                {isSubmitting
                  ? isEditMode
                    ? "正在更新..."
                    : "正在创建..."
                  : isEditMode
                    ? "更新"
                    : "创建"}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
