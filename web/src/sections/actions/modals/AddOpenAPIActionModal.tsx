"use client";

import { markdown } from "@opal/utils";
import type { RichStr } from "@opal/types";
import { useTranslations } from "next-intl";
import {
  Button,
  CopyButton,
  InputTextArea,
  Modal,
  Tooltip,
} from "@opal/components";
import { InputErrorText, InputVertical, toast } from "@opal/layouts";
import InputTextAreaField from "@/refresh-components/form/InputTextAreaField";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Hoverable } from "@opal/core";
import { validateToolDefinition } from "@/lib/tools/svc";
import debounce from "lodash/debounce";
import { DOCS_ADMINS_PATH } from "@/lib/constants";
import { Formik, Form, useFormikContext } from "formik";
import * as Yup from "yup";
import { SvgBracketCurly } from "@opal/icons";

export interface OpenAPICreationDraft {
  name: string;
  description: string;
  definition: Record<string, unknown>;
}

interface AddOpenAPIActionModalProps {
  title: string | RichStr;
  onClose: () => void;
  onBusyChange: (busy: boolean) => void;
  initialDefinition?: Record<string, unknown>;
  initialDescription?: string;
  onConfigureAuthentication: (draft: OpenAPICreationDraft) => void;
}

interface OpenAPIActionFormValues {
  description: string;
  definition: string;
}

function parseJsonWithTrailingCommas(jsonString: string) {
  const cleanedJsonString = jsonString.replace(
    /"(?:\\.|[^"\\])*"|,\s*(?=[}\]])|\b(?:True|False|None)\b/g,
    (token: string) => {
      switch (token) {
        case "True":
          return "true";
        case "False":
          return "false";
        case "None":
          return "null";
        default:
          return token.startsWith(",") ? "" : token;
      }
    }
  );
  return JSON.parse(cleanedJsonString);
}

interface FormContentProps {
  onBusyChange: (busy: boolean) => void;
  handleClose: () => void;
  title: string | RichStr;
}

function FormContent({ onBusyChange, handleClose, title }: FormContentProps) {
  const t = useTranslations("actions");
  const { values, setFieldValue, isSubmitting, submitForm } =
    useFormikContext<OpenAPIActionFormValues>();

  const validationRequest = useRef(0);
  const [definitionError, setDefinitionError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  useEffect(() => {
    onBusyChange(isSubmitting || checking);
    return () => onBusyChange(false);
  }, [isSubmitting, checking, onBusyChange]);
  const editableSchema = useMemo(() => {
    try {
      const parsed: unknown = parseJsonWithTrailingCommas(values.definition);
      if (
        typeof parsed !== "object" ||
        parsed === null ||
        Array.isArray(parsed) ||
        !("info" in parsed)
      )
        return null;
      const info = parsed.info;
      if (typeof info !== "object" || info === null || Array.isArray(info))
        return null;
      return { ...parsed, info };
    } catch {
      return null;
    }
  }, [values.definition]);
  const agentDescription =
    editableSchema &&
    "description" in editableSchema.info &&
    typeof editableSchema.info.description === "string"
      ? editableSchema.info.description
      : "";

  const handleFormat = useCallback(() => {
    if (!values.definition.trim()) {
      return;
    }

    try {
      const formatted = JSON.stringify(
        parseJsonWithTrailingCommas(values.definition),
        null,
        2
      );
      setFieldValue("definition", formatted);
      setDefinitionError(null);
    } catch {
      setDefinitionError(t("addOpenApiModal.definition.invalidJson"));
    }
  }, [values.definition, setFieldValue, t]);

  const validateDefinition = useCallback(
    async (rawDefinition: string) => {
      const request = ++validationRequest.current;
      if (!rawDefinition.trim()) {
        setDefinitionError(null);
        return false;
      }

      try {
        const parsedDefinition = parseJsonWithTrailingCommas(rawDefinition);
        const response = await validateToolDefinition({
          definition: parsedDefinition,
        });

        if (request !== validationRequest.current) return false;

        setDefinitionError(response.error);
        return !response.error;
      } catch {
        if (request !== validationRequest.current) return false;
        setDefinitionError(t("addOpenApiModal.definition.invalidJson"));
        return false;
      }
    },
    [t]
  );

  const debouncedValidateDefinition = useMemo(
    () => debounce(validateDefinition, 300),
    [validateDefinition]
  );

  useEffect(() => {
    setDefinitionError(null);
    if (values.definition.trim()) {
      debouncedValidateDefinition(values.definition);
    }

    return () => {
      debouncedValidateDefinition.cancel();
      validationRequest.current += 1;
    };
  }, [values.definition, debouncedValidateDefinition]);

  return (
    <Form className="contents">
      <Modal.Header padding={4} title={title} onClose={handleClose} />

      <Modal.Body twoTone={false} padding={6} gap={4} alignItems="stretch">
        <div className="w-full">
          <InputVertical
            withLabel="definition"
            title={t("addOpenApiModal.definition.title")}
            description={markdown(
              t("addOpenApiModal.definition.subDescription", {
                docsUrl: `${DOCS_ADMINS_PATH}/actions/openapi`,
              })
            )}
          >
            <Hoverable.Root group="definitionField" width="full">
              <div className="relative w-full">
                {values.definition.trim() && (
                  <div className="absolute z-100000 top-2 end-2 bg-background-tint-00">
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
                          disabled={checking || isSubmitting}
                          aria-label={t("addOpenApiModal.formatButton.tooltip")}
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
                    variant={
                      checking || isSubmitting
                        ? "disabled"
                        : definitionError
                          ? "error"
                          : undefined
                    }
                    rows={8}
                    placeholder={t("addOpenApiModal.definition.placeholder")}
                  />
                </div>
              </div>
            </Hoverable.Root>
          </InputVertical>
          {definitionError && (
            <InputErrorText type="error">{definitionError}</InputErrorText>
          )}
        </div>
        <InputVertical
          title={t("addOpenApiModal.humanDescription.title")}
          suffix="optional"
          description={t("addOpenApiModal.humanDescription.hint")}
          withLabel="plugin-description"
        >
          <InputTextArea
            id="plugin-description"
            value={values.description}
            onChange={(event) =>
              setFieldValue("description", event.target.value)
            }
            variant={checking || isSubmitting ? "disabled" : "primary"}
            rows={3}
          />
        </InputVertical>
        <InputVertical
          title={t("addOpenApiModal.agentDescription.title")}
          description={t("addOpenApiModal.agentDescription.hint")}
          withLabel="plugin-agent-description"
        >
          <Tooltip
            tooltip={
              !editableSchema
                ? t("addOpenApiModal.agentDescription.disabled")
                : undefined
            }
            side="top"
          >
            <div className="w-full">
              <InputTextArea
                id="plugin-agent-description"
                value={agentDescription}
                onChange={(event) => {
                  if (!editableSchema) return;
                  setFieldValue(
                    "definition",
                    JSON.stringify(
                      {
                        ...editableSchema,
                        info: {
                          ...editableSchema.info,
                          description: event.target.value,
                        },
                      },
                      null,
                      2
                    )
                  );
                }}
                variant={
                  checking || isSubmitting || !editableSchema
                    ? "disabled"
                    : "primary"
                }
                rows={3}
              />
            </div>
          </Tooltip>
        </InputVertical>
      </Modal.Body>

      <Modal.Footer padding={6}>
        <div className="ms-auto flex items-center gap-2">
          <Button
            disabled={isSubmitting || checking}
            prominence="secondary"
            type="button"
            onClick={handleClose}
          >
            {t("addOpenApiModal.cancelButton.label")}
          </Button>
          <Button
            type="button"
            disabled={!values.definition.trim() || checking}
            onClick={async () => {
              setChecking(true);
              debouncedValidateDefinition.cancel();
              const validation = validateDefinition(values.definition);
              const request = validationRequest.current;
              try {
                if (await validation) await submitForm();
              } finally {
                if (request === validationRequest.current) setChecking(false);
              }
            }}
          >
            {checking ? t("mcpSetup.checking") : t("mcpSetup.continue")}
          </Button>
        </div>
      </Modal.Footer>
    </Form>
  );
}

export default function AddOpenAPIActionModal({
  onClose,
  title,
  onBusyChange,
  initialDefinition,
  initialDescription,
  onConfigureAuthentication,
}: AddOpenAPIActionModalProps) {
  const t = useTranslations("actions");

  const validationSchema = Yup.object().shape({
    definition: Yup.string().required(t("addOpenApiModal.definition.required")),
  });

  const initialValues: OpenAPIActionFormValues = {
    description: initialDescription ?? "",
    definition: initialDefinition
      ? JSON.stringify(initialDefinition, null, 2)
      : "",
  };

  const handleSubmit = async (values: OpenAPIActionFormValues) => {
    try {
      const definition = parseJsonWithTrailingCommas(values.definition);
      onConfigureAuthentication({
        name: definition.info.title,
        description: values.description.trim(),
        definition,
      });
    } catch {
      toast.error(t("addOpenApiModal.toasts.invalidJson"));
    }
  };

  return (
    <Formik
      initialValues={initialValues}
      validationSchema={validationSchema}
      onSubmit={handleSubmit}
    >
      <FormContent
        onBusyChange={onBusyChange}
        handleClose={onClose}
        title={title}
      />
    </Formik>
  );
}
