"use client";

import { markdown } from "@opal/utils";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { Modal } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import { InputVertical, toast } from "@opal/layouts";
import InputTextAreaField from "@/refresh-components/form/InputTextAreaField";
import { useCallback, useEffect, useMemo, useState } from "react";
import { CopyButton } from "@opal/components";
import { Button, Divider } from "@opal/components";
import { Hoverable } from "@opal/core";
import { MethodSpec, ToolSnapshot } from "@/lib/tools/types";
import { can } from "@/lib/permissions/resource-actions";
import {
  validateToolDefinition,
  createCustomTool,
  updateCustomTool,
} from "@/lib/tools/svc";
import ToolItem from "@/sections/actions/ToolItem";
import debounce from "lodash/debounce";
import { DOCS_ADMINS_PATH } from "@/lib/constants";
import { useModal } from "@opal/components";
import { Formik, Form, useFormikContext } from "formik";
import * as Yup from "yup";
import {
  SvgActions,
  SvgBracketCurly,
  SvgCheckCircle,
  SvgAlertCircle,
  SvgUnplug,
} from "@opal/icons";
import InfoBlock from "@/refresh-components/messages/InfoBlock";
import { getActionIcon } from "@/lib/tools/utils";
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
  const t = useTranslations("actions");
  const { values, setFieldValue, setFieldError, dirty, isSubmitting } =
    useFormikContext<OpenAPIActionFormValues>();

  const [methodSpecs, setMethodSpecs] = useState<MethodSpec[] | null>(null);
  const [name, setName] = useState<string | null>(null);
  const [description, setDescription] = useState<string | undefined>(undefined);
  const [url, setUrl] = useState<string | undefined>(undefined);

  const isEditMode = Boolean(existingTool);
  // Editing auth manages the action's OAuth config (owner-or-admin); gate on the same
  // server-stamped capability as the card.
  const canEditAuthentication = existingTool
    ? can(existingTool, "authenticate")
    : false;

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
      setFieldError("definition", t("addOpenApiModal.definition.invalidJson"));
    }
  }, [values.definition, setFieldValue, setFieldError, t]);

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
        setFieldError(
          "definition",
          t("addOpenApiModal.definition.invalidJson")
        );
      }
    },
    [t]
  );

  const debouncedValidateDefinition = useMemo(
    () => debounce(validateDefinition, 300),
    [validateDefinition]
  );

  const modalTitle = isEditMode
    ? t("addOpenApiModal.editHeader.title")
    : t("addOpenApiModal.addHeader.title");
  const modalDescription = isEditMode
    ? t("addOpenApiModal.editHeader.description")
    : t("addOpenApiModal.addHeader.description");
  const primaryButtonLabel = isSubmitting
    ? isEditMode
      ? t("addOpenApiModal.submitButton.savingLabel")
      : t("addOpenApiModal.submitButton.addingLabel")
    : isEditMode
      ? t("addOpenApiModal.submitButton.saveLabel")
      : t("addOpenApiModal.submitButton.addLabel");

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
        ? t("addOpenApiModal.authStatus.oauthNamedDescription", {
            name: existingTool.oauth_config_name,
          })
        : t("addOpenApiModal.authStatus.oauthDescription");
    }
    if (hasCustomHeaders) {
      return t("addOpenApiModal.authStatus.headersDescription");
    }
    if (hasPassthroughAuth) {
      return t("addOpenApiModal.authStatus.passthroughDescription");
    }
    return "";
  }, [existingTool, hasOAuthConfig, hasCustomHeaders, hasPassthroughAuth, t]);

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
          title={t("addOpenApiModal.definition.title")}
          subDescription={markdown(
            t("addOpenApiModal.definition.subDescription", {
              docsUrl: `${DOCS_ADMINS_PATH}/actions/openapi`,
            })
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
                        tooltip={t("addOpenApiModal.copyButton.tooltip")}
                      />
                      <Button
                        prominence="tertiary"
                        size="sm"
                        icon={SvgBracketCurly}
                        tooltip={t("addOpenApiModal.formatButton.tooltip")}
                        onClick={handleFormat}
                      />
                    </div>
                  </Hoverable.Item>
                </div>
              )}
              <div className="font-main-ui-mono">
                <InputTextAreaField
                  name="definition"
                  rows={14}
                  placeholder={t("addOpenApiModal.definition.placeholder")}
                />
              </div>
            </div>
          </Hoverable.Root>
        </InputVertical>

        <Divider paddingParallel={0} paddingPerpendicular={0} />

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
                description={t("addOpenApiModal.serverUrl.description")}
              />
            )}
            <Divider paddingParallel={0} paddingPerpendicular={0} />
            <Section gap={2}>
              {methodSpecs.map((method) => (
                <ToolItem
                  key={`${method.method}-${method.path}-${method.name}`}
                  name={method.name}
                  description={
                    method.summary || t("addOpenApiModal.method.noSummary")
                  }
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
            title={t("addOpenApiModal.empty.title")}
            icon={SvgActions}
            description={t("addOpenApiModal.empty.description")}
          />
        )}

        {showAuthenticationStatus && (
          <Section
            flexDirection="row"
            justifyContent="between"
            alignItems="start"
            gap={4}
          >
            <Section gap={1} alignItems="start">
              <Section
                flexDirection="row"
                gap={2}
                alignItems="center"
                width="fit"
              >
                <SvgCheckCircle className="w-4 h-4 stroke-status-success-05" />
                <Text>
                  {existingTool?.enabled
                    ? t("addOpenApiModal.authStatus.enabledTitle")
                    : t("addOpenApiModal.authStatus.configuredTitle")}
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
              gap={2}
              alignItems="center"
              width="fit"
            >
              <Button
                icon={SvgUnplug}
                prominence="tertiary"
                type="button"
                tooltip={t("addOpenApiModal.disableButton.tooltip")}
                onClick={() => {
                  if (!existingTool || !onDisconnectTool) {
                    return;
                  }
                  onDisconnectTool(existingTool);
                }}
              />
              <Button
                disabled={!onEditAuthentication || !canEditAuthentication}
                tooltip={
                  !canEditAuthentication
                    ? t("addOpenApiModal.editConfigsButton.disabledTooltip")
                    : undefined
                }
                prominence="secondary"
                type="button"
                onClick={handleEditAuthenticationClick}
              >
                {t("addOpenApiModal.editConfigsButton.label")}
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
          {t("addOpenApiModal.cancelButton.label")}
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
  const t = useTranslations("actions");
  const { isOpen, toggle } = useModal();

  const validationSchema = Yup.object().shape({
    definition: Yup.string().required(t("addOpenApiModal.definition.required")),
  });

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
      toast.error(t("addOpenApiModal.toasts.invalidJson"));
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
          toast.success(t("addOpenApiModal.toasts.actionUpdated"));
          handleClose();
          if (response.data && onUpdate) {
            onUpdate(response.data);
          }
        }
      } catch (error) {
        console.error("Error updating OpenAPI action:", error);
        toast.error(t("addOpenApiModal.toasts.updateFailed"));
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
        toast.success(t("addOpenApiModal.toasts.actionCreated"));
        handleClose();
        if (response.data && onSuccess) {
          onSuccess(response.data);
        }
      }
    } catch (error) {
      console.error("Error creating OpenAPI action:", error);
      toast.error(t("addOpenApiModal.toasts.createFailed"));
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
