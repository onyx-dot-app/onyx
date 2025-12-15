"use client";

import Link from "next/link";
import Modal from "@/refresh-components/Modal";
import Button from "@/refresh-components/buttons/Button";
import InputTextArea from "@/refresh-components/inputs/InputTextArea";
import Text from "@/refresh-components/texts/Text";
import { FormField } from "@/refresh-components/form/FormField";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import Separator from "@/refresh-components/Separator";
import { useCallback, useEffect, useMemo, useState } from "react";
import CopyIconButton from "@/refresh-components/buttons/CopyIconButton";
import IconButton from "@/refresh-components/buttons/IconButton";
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
import { Formik, Form } from "formik";
import * as Yup from "yup";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import {
  SvgActions,
  SvgBracketCurly,
  SvgCheckCircle,
  SvgAlertCircle,
  SvgUnplug,
} from "@opal/icons";
import InfoBlock from "@/refresh-components/messages/InfoBlock";
import { getActionIcon } from "@/lib/tools/mcpUtils";

interface AddOpenAPIActionModalProps {
  skipOverlay?: boolean;
  onSuccess?: (tool: ToolSnapshot) => void;
  onUpdate?: (tool: ToolSnapshot) => void;
  setPopup: (popup: PopupSpec) => void;
  existingTool?: ToolSnapshot | null;
  onClose?: () => void;
  onEditAuthentication?: (tool: ToolSnapshot) => void;
  onDisconnectTool?: (tool: ToolSnapshot) => Promise<void> | void;
}

interface OpenAPIActionFormValues {
  definition: string;
}

const validationSchema = Yup.object().shape({
  definition: Yup.string().required("OpenAPI schema definition is required"),
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

interface SchemaActionsProps {
  definition: string;
  onFormat: () => void;
}

function SchemaActions({ definition, onFormat }: SchemaActionsProps) {
  return (
    <div className="flex flex-col">
      <CopyIconButton
        tertiary
        getCopyText={() => definition}
        tooltip="Copy definition"
      />
      <IconButton
        tertiary
        icon={SvgBracketCurly}
        tooltip="Format definition"
        onClick={onFormat}
      />
    </div>
  );
}
export default function AddOpenAPIActionModal({
  skipOverlay = false,
  onSuccess,
  onUpdate,
  setPopup,
  existingTool = null,
  onClose,
  onEditAuthentication,
  onDisconnectTool,
}: AddOpenAPIActionModalProps) {
  const { isOpen, toggle } = useModal();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [methodSpecs, setMethodSpecs] = useState<MethodSpec[] | null>(null);
  const [name, setName] = useState<string | null>(null);
  const [description, setDescription] = useState<string | undefined>(undefined);
  const [url, setUrl] = useState<string | undefined>(undefined);
  const [definitionError, setDefinitionError] = useState<string | null>(null);
  const isEditMode = Boolean(existingTool);

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

  const handleFormat = useCallback(
    (
      definition: string,
      setFieldValue: (field: string, value: any) => void
    ) => {
      if (!definition.trim()) {
        return;
      }

      try {
        const formatted = prettifyDefinition(
          parseJsonWithTrailingCommas(definition)
        );
        setFieldValue("definition", formatted);
        setDefinitionError(null);
      } catch {
        setDefinitionError("Invalid JSON format");
      }
    },
    []
  );

  const validateDefinition = useCallback(async (rawDefinition: string) => {
    if (!rawDefinition.trim()) {
      setMethodSpecs(null);
      setDefinitionError(null);
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
        setDefinitionError(response.error);
      } else {
        setMethodSpecs(response.data ?? []);
        setDefinitionError(null);
      }
    } catch {
      setMethodSpecs(null);
      setDefinitionError("Invalid JSON format");
    }
  }, []);

  const debouncedValidateDefinition = useMemo(
    () => debounce(validateDefinition, 300),
    [validateDefinition]
  );

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
        : "OAuth authentication configured";
    }
    if (hasCustomHeaders) {
      return "Custom authentication headers configured";
    }
    if (hasPassthroughAuth) {
      return "Passthrough authentication enabled";
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

  const handleSubmit = async (values: OpenAPIActionFormValues) => {
    setIsSubmitting(true);

    try {
      const parsedDefinition = parseJsonWithTrailingCommas(values.definition);
      const derivedName = parsedDefinition?.info?.title;
      const derivedDescription = parsedDefinition?.info?.description;

      if (isEditMode && existingTool) {
        const updatePayload: {
          name?: string;
          description?: string;
          definition: Record<string, any>;
        } = {
          definition: parsedDefinition,
        };

        if (derivedName) {
          updatePayload.name = derivedName;
        }

        if (derivedDescription) {
          updatePayload.description = derivedDescription;
        }

        const response = await updateCustomTool(existingTool.id, updatePayload);

        if (response.error) {
          setPopup({
            message: response.error,
            type: "error",
          });
        } else {
          setPopup({
            message: "OpenAPI action updated successfully",
            type: "success",
          });
          handleClose();
          if (response.data && onUpdate) {
            onUpdate(response.data);
          }
        }
        return;
      }

      const response = await createCustomTool({
        name: derivedName,
        description: derivedDescription || undefined,
        definition: parsedDefinition,
        custom_headers: [],
        passthrough_auth: false,
      });

      if (response.error) {
        setPopup({
          message: response.error,
          type: "error",
        });
      } else {
        setPopup({
          message: "OpenAPI action created successfully",
          type: "success",
        });
        handleClose();
        if (response.data && onSuccess) {
          onSuccess(response.data);
        }
      }
    } catch (error) {
      console.error("Error creating OpenAPI action:", error);
      setPopup({
        message: isEditMode
          ? "Failed to update OpenAPI action"
          : "Failed to create OpenAPI action",
        type: "error",
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  const modalTitle = isEditMode ? "Edit OpenAPI action" : "Add OpenAPI action";
  const modalDescription = isEditMode
    ? "Update the OpenAPI schema for this action."
    : "Add OpenAPI schema to add custom actions.";
  const primaryButtonLabel = isSubmitting
    ? isEditMode
      ? "Saving..."
      : "Adding..."
    : isEditMode
      ? "Save Changes"
      : "Add Action";

  return (
    <>
      <Modal open={isOpen} onOpenChange={handleModalClose}>
        <Modal.Content tall skipOverlay={skipOverlay}>
          <Formik
            initialValues={initialValues}
            validationSchema={validationSchema}
            onSubmit={handleSubmit}
            enableReinitialize
          >
            {({
              values,
              errors,
              touched,
              handleChange,
              handleBlur,
              setFieldValue,
              dirty,
            }) => {
              // Effect for validating definition
              useEffect(() => {
                if (!values.definition.trim()) {
                  setMethodSpecs(null);
                  setDefinitionError(null);
                  debouncedValidateDefinition.cancel();
                  return () => {
                    debouncedValidateDefinition.cancel();
                  };
                }

                debouncedValidateDefinition(values.definition);

                return () => {
                  debouncedValidateDefinition.cancel();
                };
              }, [values.definition]);

              return (
                <Form className="gap-0">
                  <Modal.Header
                    icon={SvgActions}
                    title={modalTitle}
                    description={modalDescription}
                    onClose={handleClose}
                    className="p-4 w-full"
                  />

                  <Modal.Body className="bg-background-tint-01 p-4 flex flex-col gap-4 overflow-y-auto">
                    <FormField
                      id="openapi-schema"
                      name="definition"
                      className="gap-2"
                      state={
                        (errors.definition && touched.definition) ||
                        definitionError
                          ? "error"
                          : touched.definition
                            ? "success"
                            : "idle"
                      }
                    >
                      <FormField.Label className="tracking-tight">
                        OpenAPI Schema Definition
                      </FormField.Label>
                      <FormField.Control asChild>
                        <InputTextArea
                          id="definition"
                          name="definition"
                          value={values.definition}
                          onChange={handleChange}
                          onBlur={handleBlur}
                          rows={14}
                          placeholder="Enter your OpenAPI schema here"
                          className="text-text-04 font-main-ui-mono"
                          action={
                            values.definition.trim() ? (
                              <SchemaActions
                                definition={values.definition}
                                onFormat={() =>
                                  handleFormat(values.definition, setFieldValue)
                                }
                              />
                            ) : null
                          }
                        />
                      </FormField.Control>
                      <FormField.Description>
                        Specify an OpenAPI schema that defines the APIs you want
                        to make available as part of this action. Learn more
                        about{" "}
                        <span className="inline-flex">
                          <SimpleTooltip
                            tooltip={`Open ${DOCS_ADMINS_PATH}/actions/openapi`}
                            side="top"
                          >
                            <Link
                              href={`${DOCS_ADMINS_PATH}/actions/openapi`}
                              target="_blank"
                              rel="noreferrer"
                              className="underline"
                            >
                              OpenAPI actions
                            </Link>
                          </SimpleTooltip>
                        </span>
                        .
                      </FormField.Description>
                      <FormField.Message
                        messages={{
                          error: definitionError || errors.definition,
                        }}
                      />
                    </FormField>

                    <Separator className="my-0 py-0" />

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
                            description="URL found in the schema. Only connect to servers you trust."
                          />
                        )}
                        <Separator className="my-0 py-0" />
                        <div className="flex flex-col gap-2">
                          {methodSpecs.map((method) => (
                            <ToolItem
                              key={`${method.method}-${method.path}-${method.name}`}
                              name={method.name}
                              description={
                                method.summary || "No summary provided"
                              }
                              variant="openapi"
                              openApiMetadata={{
                                method: method.method,
                                path: method.path,
                              }}
                            />
                          ))}
                        </div>
                      </>
                    ) : (
                      <div className="flex flex-row gap-3 items-start p-1.5 rounded-08 border border-border-01 border-dashed">
                        <div className="rounded-08 bg-background-tint-01 p-1 flex items-center justify-center">
                          <SvgActions className="size-4 stroke-text-03" />
                        </div>
                        <div className="flex flex-col gap-1">
                          <Text mainUiAction text03>
                            No actions found
                          </Text>
                          <Text secondaryBody text03>
                            Provide OpenAPI schema to preview actions here.
                          </Text>
                        </div>
                      </div>
                    )}
                    {showAuthenticationStatus && (
                      <FormField state="idle">
                        <div className="flex items-start justify-between w-full">
                          <div className="flex flex-col gap-0 items-start flex-1">
                            <FormField.Label
                              leftIcon={
                                <SvgCheckCircle className="w-4 h-4 stroke-status-success-05" />
                              }
                            >
                              {existingTool?.enabled
                                ? "Authenticated & Enabled"
                                : "Authentication configured"}
                            </FormField.Label>
                            {authenticationDescription && (
                              <FormField.Description className="pl-5">
                                {authenticationDescription}
                              </FormField.Description>
                            )}
                          </div>
                          <FormField.Control asChild>
                            <div className="flex gap-2 items-center justify-end">
                              <IconButton
                                icon={SvgUnplug}
                                tertiary
                                type="button"
                                tooltip="Disable action"
                                onClick={() => {
                                  if (!existingTool || !onDisconnectTool) {
                                    return;
                                  }
                                  onDisconnectTool(existingTool);
                                }}
                              />
                              <Button
                                secondary
                                type="button"
                                onClick={handleEditAuthenticationClick}
                                disabled={!onEditAuthentication}
                              >
                                Edit Configs
                              </Button>
                            </div>
                          </FormField.Control>
                        </div>
                      </FormField>
                    )}
                  </Modal.Body>

                  <Modal.Footer className="w-full p-4 gap-2 bg-background-tint-00">
                    <Button
                      main
                      secondary
                      type="button"
                      onClick={handleClose}
                      disabled={isSubmitting}
                    >
                      Cancel
                    </Button>
                    <Button
                      main
                      primary
                      type="submit"
                      disabled={isSubmitting || !dirty}
                    >
                      {primaryButtonLabel}
                    </Button>
                  </Modal.Footer>
                </Form>
              );
            }}
          </Formik>
        </Modal.Content>
      </Modal>
    </>
  );
}
