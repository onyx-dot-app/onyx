"use client";

import Link from "next/link";
import Modal from "@/refresh-components/Modal";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import * as InputLayouts from "@/layouts/input-layouts";
import InputTextAreaField from "@/refresh-components/form/InputTextAreaField";
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
import { Formik, Form, useFormikContext } from "formik";
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
import { Section } from "@/layouts/general-layouts";
import EmptyMessage from "@/refresh-components/EmptyMessage";

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
      setFieldError("definition", "Invalid JSON format");
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
        setFieldError("definition", "Invalid JSON format");
      }
    },
    []
  );

  const debouncedValidateDefinition = useMemo(
    () => debounce(validateDefinition, 300),
    [validateDefinition]
  );

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
        <InputLayouts.Vertical
          name="definition"
          label="OpenAPI Schema Definition"
          subDescription={
            <>
              Specify an OpenAPI schema that defines the APIs you want to make
              available as part of this action. Learn more about{" "}
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
            </>
          }
        >
          <div className="group/DefinitionTextAreaField relative">
            {values.definition.trim() && (
              <div className="invisible group-hover/DefinitionTextAreaField:visible absolute z-[100000] top-2 right-2 bg-background-tint-00">
                <CopyIconButton
                  internal
                  getCopyText={() => values.definition}
                  tooltip="Copy definition"
                />
                <IconButton
                  internal
                  icon={SvgBracketCurly}
                  tooltip="Format definition"
                  onClick={handleFormat}
                />
              </div>
            )}
            <InputTextAreaField
              name="definition"
              rows={14}
              placeholder="Enter your OpenAPI schema here"
              className="font-main-ui-mono"
            />
          </div>
        </InputLayouts.Vertical>

        <Separator noPadding />

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
            <Separator noPadding />
            <Section gap={0.5}>
              {methodSpecs.map((method) => (
                <ToolItem
                  key={`${method.method}-${method.path}-${method.name}`}
                  name={method.name}
                  description={method.summary || "No summary provided"}
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
          <EmptyMessage
            title="No Actions Found"
            icon={SvgActions}
            description="Provide OpenAPI schema to preview actions here."
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
              <Section flexDirection="row" gap={0.5} alignItems="center" fit>
                <SvgCheckCircle className="w-4 h-4 stroke-status-success-05" />
                <Text>
                  {existingTool?.enabled
                    ? "Authenticated & Enabled"
                    : "Authentication configured"}
                </Text>
              </Section>
              {authenticationDescription && (
                <Text secondaryBody text03 className="pl-5">
                  {authenticationDescription}
                </Text>
              )}
            </Section>
            <Section flexDirection="row" gap={0.5} alignItems="center" fit>
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
            </Section>
          </Section>
        )}
      </Modal.Body>

      <Modal.Footer>
        <Button
          main
          secondary
          type="button"
          onClick={handleClose}
          disabled={isSubmitting}
        >
          Cancel
        </Button>
        <Button main primary type="submit" disabled={isSubmitting || !dirty}>
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
  setPopup,
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
      setPopup({
        message: "Invalid JSON format in OpenAPI schema definition",
        type: "error",
      });
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
      } catch (error) {
        console.error("Error updating OpenAPI action:", error);
        setPopup({
          message: "Failed to update OpenAPI action",
          type: "error",
        });
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
        message: "Failed to create OpenAPI action",
        type: "error",
      });
    }
  };

  return (
    <Modal open={isOpen} onOpenChange={handleModalClose}>
      <Modal.Content tall skipOverlay={skipOverlay}>
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
