"use client";

import { markdown } from "@opal/utils";
import Link from "next/link";
import Modal from "@/refresh-components/Modal";
import Text from "@/refresh-components/texts/Text";
import { InputVertical } from "@opal/layouts";
import InputTextAreaField from "@/refresh-components/form/InputTextAreaField";
import { useCallback, useEffect, useMemo, useState } from "react";
import { CopyButton } from "@opal/components";
import { Button, Divider } from "@opal/components";
import { Hoverable } from "@opal/core";
import { MethodSpec, ToolSnapshot } from "@/lib/tools/interfaces";
import {
  validateToolDefinition,
  createCustomTool,
  updateCustomTool,
} from "@/lib/tools/openApiService";
import ToolItem from "@/sections/actions/ToolItem";
import debounce from "lodash/debounce";
import { DOCS_ADMINS_PATH } from "@/lib/constants";
import { useModal } from "@/refresh-components/contexts/ModalContext";
import { Formik, Form, useFormikContext } from "formik";
import * as Yup from "yup";
import { toast } from "@/hooks/useToast";
import {
  SvgActions,
  SvgBracketCurly,
  SvgCheckCircle,
  SvgAlertCircle,
  SvgUnplug,
} from "@opal/icons";
import InfoBlock from "@/refresh-components/messages/InfoBlock";
import { getActionIcon } from "@/lib/tools/mcpUtils";
import { Section } from "@/layouts/general-layouts";
import { EmptyMessageCard } from "@opal/components";

interface AddOpenAPIActionModalProps {
  skipOverlay?: boolean;
  onSuccess?: (tool: ToolSnapshot) => void;
  onUpdate?: (tool: ToolSnapshot) => void;
  existingTool?: ToolSnapshot | null;
  onClose?: () => void;
  onEditAuthentication?: (tool: ToolSnapshot) => void;
  onDisconnectTool?: (tool: ToolSnapshot) => Promise<void> | void;
}

interface OpenAPIActionFormValues {
  definition: string;
}

const validationSchema = Yup.object().shape({
  definition: Yup.string().required("请输入 OpenAPI schema 定义"),
});

function parseJsonWithTrailingCommas(jsonString: string) {
  // Regular expression to remove trailing commas before } or ]
  let cleanedJsonString = jsonString.replace(/,\s*([}\]])/g, "$1");
  // Replace True with true, False with false, and None with null
  cleanedJsonString = cleanedJsonString
    .replace(/\bTrue\b/g, "true")
    .replace(/\bFalse\b/g, "false")
    .replace(/\bNone\b/g, "null");
  // Now parse the cleaned JSON string
  return JSON.parse(cleanedJsonString);
}

function prettifyDefinition(definition: any) {
  return JSON.stringify(definition, null, 2);
}

interface FormContentProps {
  handleClose: () => void;
  existingTool: ToolSnapshot | null;
  onEditAuthentication?: (tool: ToolSnapshot) => void;
  onDisconnectTool?: (tool: ToolSnapshot) => Promise<void> | void;
}

function FormContent({
  handleClose,
  existingTool,
  onEditAuthentication,
  onDisconnectTool,
}: FormContentProps) {
  const { values, setFieldValue, setFieldError, dirty, isSubmitting } =
    useFormikContext<OpenAPIActionFormValues>();

  const [methodSpecs, setMethodSpecs] = useState<MethodSpec[] | null>(null);
  const [name, setName] = useState<string | null>(null);
  const [description, setDescription] = useState<string | undefined>(undefined);
  const [url, setUrl] = useState<string | undefined>(undefined);

  const isEditMode = Boolean(existingTool);

  const handleFormat = useCallback(() => {
    if (!values.definition.trim()) {
      return;
    }

    try {
      const formatted = prettifyDefinition(
        parseJsonWithTrailingCommas(values.definition)
      );
      setFieldValue("definition", formatted);
      setFieldError("definition", "");
    } catch {
      setFieldError("definition", "JSON 格式无效");
    }
  }, [values.definition, setFieldValue, setFieldError]);

  const validateDefinition = useCallback(
    async (
      rawDefinition: string,
      setFieldError: (field: string, message: string) => void
    ) => {
      if (!rawDefinition.trim()) {
        setMethodSpecs(null);
        setFieldError("definition", "");
        return;
      }

      try {
        const parsedDefinition = parseJsonWithTrailingCommas(rawDefinition);
        const derivedName = parsedDefinition?.info?.title;
        const derivedDescription = parsedDefinition?.info?.description;
        const derivedUrl = parsedDefinition?.servers?.[0]?.url;

        setName(derivedName);
        setDescription(derivedDescription);
        setUrl(derivedUrl);

        const response = await validateToolDefinition({
          definition: parsedDefinition,
        });

        if (response.error) {
          setMethodSpecs(null);
          setFieldError("definition", response.error);
        } else {
          setMethodSpecs(response.data ?? []);
          setFieldError("definition", "");
        }
      } catch {
        setMethodSpecs(null);
        setFieldError("definition", "JSON 格式无效");
      }
    },
    []
  );

  const debouncedValidateDefinition = useMemo(
    () => debounce(validateDefinition, 300),
    [validateDefinition]
  );

  const modalTitle = isEditMode ? "编辑 OpenAPI 动作" : "添加 OpenAPI 动作";
  const modalDescription = isEditMode
    ? "更新此动作的 OpenAPI schema。"
    : "添加 OpenAPI schema 以创建自定义动作。";
  const primaryButtonLabel = isSubmitting
    ? isEditMode
      ? "正在保存..."
      : "正在添加..."
    : isEditMode
      ? "保存更改"
      : "添加动作";

  const hasOAuthConfig = Boolean(existingTool?.oauth_config_id);
  const hasCustomHeaders =
    Array.isArray(existingTool?.custom_headers) &&
    (existingTool?.custom_headers?.length ?? 0) > 0;
  const hasPassthroughAuth = Boolean(existingTool?.passthrough_auth);
  const hasAuthenticationConfigured =
    hasOAuthConfig || hasCustomHeaders || hasPassthroughAuth;
  const authenticationDescription = useMemo(() => {
    if (!existingTool) {
      return "";
    }
    if (hasOAuthConfig) {
      return existingTool.oauth_config_name
        ? `OAuth connected via ${existingTool.oauth_config_name}`
        : "已配置 OAuth 认证";
    }
    if (hasCustomHeaders) {
      return "已配置自定义认证 Header";
    }
    if (hasPassthroughAuth) {
      return "已启用透传认证";
    }
    return "";
  }, [existingTool, hasOAuthConfig, hasCustomHeaders, hasPassthroughAuth]);

  const showAuthenticationStatus = Boolean(
    isEditMode && existingTool?.enabled && hasAuthenticationConfigured
  );

  const handleEditAuthenticationClick = useCallback(() => {
    if (!existingTool || !onEditAuthentication) {
      return;
    }
    handleClose();
    onEditAuthentication(existingTool);
  }, [existingTool, onEditAuthentication, handleClose]);

  useEffect(() => {
    if (!values.definition.trim()) {
      setMethodSpecs(null);
      setFieldError("definition", "");
      debouncedValidateDefinition.cancel();
      return () => {
        debouncedValidateDefinition.cancel();
      };
    }

    debouncedValidateDefinition(values.definition, setFieldError);

    return () => {
      debouncedValidateDefinition.cancel();
    };
  }, [
    values.definition,
    debouncedValidateDefinition,
    setFieldError,
    setMethodSpecs,
  ]);

  return (
    <Form>
      <Modal.Header
        icon={SvgActions}
        title={modalTitle}
        description={modalDescription}
        onClose={handleClose}
      />

      <Modal.Body>
        <InputVertical
          withLabel="definition"
          title="OpenAPI Schema 定义"
          subDescription={markdown(
            `指定一个 OpenAPI schema，用来定义此动作可调用的 API。` +
              `你可以在 schema 的任意位置使用占位符 \`CHAT_SESSION_ID\`、\`MESSAGE_ID\`、\`USER_ID\` 和 \`USER_EMAIL\` ` +
              `（例如服务 URL、路径、参数默认值），调用时会替换为当前请求的值。` +
              `了解更多：[OpenAPI 动作](${DOCS_ADMINS_PATH}/actions/openapi)。`
          )}
        >
          <Hoverable.Root group="definitionField" width="full">
            <div className="relative w-full">
              {values.definition.trim() && (
                <div className="absolute z-100000 top-2 right-2 bg-background-tint-00">
                  <Hoverable.Item
                    group="definitionField"
                    variant="appear-on-hover"
                  >
                    <div className="flex">
                      <CopyButton
                        prominence="tertiary"
                        size="sm"
                        getCopyText={() => values.definition}
                        tooltip="复制定义"
                      />
                      <Button
                        prominence="tertiary"
                        size="sm"
                        icon={SvgBracketCurly}
                        tooltip="格式化定义"
                        onClick={handleFormat}
                      />
                    </div>
                  </Hoverable.Item>
                </div>
              )}
              <InputTextAreaField
                name="definition"
                rows={14}
                placeholder="在此输入 OpenAPI schema"
                className="font-main-ui-mono"
              />
            </div>
          </Hoverable.Root>
        </InputVertical>

        <Divider paddingParallel="fit" paddingPerpendicular="fit" />

        {methodSpecs && methodSpecs.length > 0 ? (
          <>
            {name && (
              <InfoBlock
                icon={getActionIcon(url || "", name || "")}
                title={name}
                description={description}
              />
            )}
            {url && (
              <InfoBlock
                icon={SvgAlertCircle}
                title={url || ""}
                description="在 schema 中发现 URL。只连接你信任的服务。"
              />
            )}
            <Divider paddingParallel="fit" paddingPerpendicular="fit" />
            <Section gap={0.5}>
              {methodSpecs.map((method) => (
                <ToolItem
                  key={`${method.method}-${method.path}-${method.name}`}
                  name={method.name}
                  description={method.summary || "未提供摘要"}
                  variant="openapi"
                  openApiMetadata={{
                    method: method.method,
                    path: method.path,
                  }}
                />
              ))}
            </Section>
          </>
        ) : (
          <EmptyMessageCard
            sizePreset="main-ui"
            title="未找到动作"
            icon={SvgActions}
            description="提供 OpenAPI schema 后即可在此预览动作。"
          />
        )}

        {showAuthenticationStatus && (
          <Section
            flexDirection="row"
            justifyContent="between"
            alignItems="start"
            gap={1}
          >
            <Section gap={0.25} alignItems="start">
              <Section
                flexDirection="row"
                gap={0.5}
                alignItems="center"
                width="fit"
              >
                <SvgCheckCircle className="w-4 h-4 stroke-status-success-05" />
                <Text>
                  {existingTool?.enabled
                    ? "已认证并启用"
                    : "已配置认证"}
                </Text>
              </Section>
              {authenticationDescription && (
                <Text secondaryBody text03 className="pl-5">
                  {authenticationDescription}
                </Text>
              )}
            </Section>
            <Section
              flexDirection="row"
              gap={0.5}
              alignItems="center"
              width="fit"
            >
              <Button
                icon={SvgUnplug}
                prominence="tertiary"
                type="button"
                tooltip="停用动作"
                onClick={() => {
                  if (!existingTool || !onDisconnectTool) {
                    return;
                  }
                  onDisconnectTool(existingTool);
                }}
              />
              <Button
                disabled={!onEditAuthentication}
                prominence="secondary"
                type="button"
                onClick={handleEditAuthenticationClick}
              >
                编辑配置
              </Button>
            </Section>
          </Section>
        )}
      </Modal.Body>

      <Modal.Footer>
        <Button
          disabled={isSubmitting}
          prominence="secondary"
          type="button"
          onClick={handleClose}
        >
          取消
        </Button>
        <Button disabled={isSubmitting || !dirty} type="submit">
          {primaryButtonLabel}
        </Button>
      </Modal.Footer>
    </Form>
  );
}

export default function AddOpenAPIActionModal({
  skipOverlay = false,
  onSuccess,
  onUpdate,
  existingTool = null,
  onClose,
  onEditAuthentication,
  onDisconnectTool,
}: AddOpenAPIActionModalProps) {
  const { isOpen, toggle } = useModal();

  const handleModalClose = useCallback(
    (open: boolean) => {
      toggle(open);
      if (!open) {
        onClose?.();
      }
    },
    [toggle, onClose]
  );

  const handleClose = useCallback(() => {
    handleModalClose(false);
  }, [handleModalClose]);

  const initialValues: OpenAPIActionFormValues = useMemo(
    () => ({
      definition: existingTool?.definition
        ? prettifyDefinition(existingTool.definition)
        : "",
    }),
    [existingTool]
  );

  const handleSubmit = async (values: OpenAPIActionFormValues) => {
    let parsedDefinition;
    try {
      parsedDefinition = parseJsonWithTrailingCommas(values.definition);
    } catch (error) {
      console.error("Error parsing OpenAPI definition:", error);
      toast.error("OpenAPI schema 定义中的 JSON 格式无效");
      return;
    }

    const derivedName = parsedDefinition?.info?.title;
    const derivedDescription = parsedDefinition?.info?.description;

    if (existingTool) {
      try {
        const updatePayload: {
          name?: string;
          description?: string;
          definition: Record<string, any>;
          custom_headers?: { key: string; value: string }[];
          passthrough_auth?: boolean;
          oauth_config_id?: number | null;
        } = {
          definition: parsedDefinition,
          custom_headers: existingTool.custom_headers,
          passthrough_auth: existingTool.passthrough_auth,
          oauth_config_id: existingTool.oauth_config_id,
        };

        if (derivedName) {
          updatePayload.name = derivedName;
        }

        if (derivedDescription) {
          updatePayload.description = derivedDescription;
        }

        const response = await updateCustomTool(existingTool.id, updatePayload);

        if (response.error) {
          toast.error(response.error);
        } else {
          toast.success("OpenAPI 动作已更新");
          handleClose();
          if (response.data && onUpdate) {
            onUpdate(response.data);
          }
        }
      } catch (error) {
        console.error("Error updating OpenAPI action:", error);
        toast.error("更新 OpenAPI 动作失败");
      }
      return;
    }

    try {
      const response = await createCustomTool({
        name: derivedName,
        description: derivedDescription || undefined,
        definition: parsedDefinition,
        custom_headers: [],
        passthrough_auth: false,
      });

      if (response.error) {
        toast.error(response.error);
      } else {
        toast.success("OpenAPI 动作已创建");
        handleClose();
        if (response.data && onSuccess) {
          onSuccess(response.data);
        }
      }
    } catch (error) {
      console.error("Error creating OpenAPI action:", error);
      toast.error("创建 OpenAPI 动作失败");
    }
  };

  return (
    <Modal open={isOpen} onOpenChange={handleModalClose}>
      <Modal.Content width="sm" height="lg" skipOverlay={skipOverlay}>
        <Formik
          initialValues={initialValues}
          validationSchema={validationSchema}
          onSubmit={handleSubmit}
          enableReinitialize
        >
          <FormContent
            handleClose={handleClose}
            existingTool={existingTool}
            onEditAuthentication={onEditAuthentication}
            onDisconnectTool={onDisconnectTool}
          />
        </Formik>
      </Modal.Content>
    </Modal>
  );
}
