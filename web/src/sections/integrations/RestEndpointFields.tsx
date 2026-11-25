"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  InputSingleUpload,
  InputTextArea,
  InputTypeIn,
} from "@opal/components";
import { InputErrorText, InputVertical, Section, toast } from "@opal/layouts";
import { importOpenApiSpec } from "@/lib/integrations/svc";
import type {
  EndpointLineError,
  OpenApiConfigView,
} from "@/lib/integrations/types";
import { specBaseUrl } from "@/sections/integrations/detectApi";

/** The REST endpoint form: a base URL and one endpoint per line. */
export interface RestDraft {
  /** The imported or stored document that the lines edit; null for none. */
  document: string | null;
  baseUrl: string;
  endpoints: string;
}

export const EMPTY_REST: RestDraft = {
  document: null,
  baseUrl: "",
  endpoints: "",
};

export function restDraftFrom(view: OpenApiConfigView): RestDraft {
  return {
    document: view.openapi_document,
    baseUrl: view.base_url,
    endpoints: view.endpoints.join("\n"),
  };
}

interface RestEndpointFieldsProps {
  draft: RestDraft;
  onChange: (draft: RestDraft) => void;
  lineErrors: EndpointLineError[];
  showErrors: boolean;
  /** Also true while an import runs; the parent holds that state. */
  disabled: boolean;
  onImportingChange: (importing: boolean) => void;
}

export default function RestEndpointFields({
  draft,
  onChange,
  lineErrors,
  showErrors,
  disabled,
  onImportingChange,
}: RestEndpointFieldsProps) {
  const t = useTranslations("admin.integrations.add.rest");
  const [specUrl, setSpecUrl] = useState("");

  async function runImport(
    body: { openapi_document: string } | { spec_url: string }
  ) {
    onImportingChange(true);
    try {
      const view = await importOpenApiSpec(body);
      const specUrl = "spec_url" in body ? body.spec_url : null;
      onChange({
        ...restDraftFrom(view),
        baseUrl: specBaseUrl(view.base_url, specUrl) ?? view.base_url,
      });
      toast.success(t("import.done", { count: view.endpoints.length }));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t("import.failed"));
    } finally {
      onImportingChange(false);
    }
  }

  return (
    <>
      <InputVertical
        title={t("import.title")}
        description={t("import.description")}
        suffix="optional"
      >
        <Section gap={2} alignItems="stretch" height="auto">
          <InputSingleUpload
            accept=".json,.yaml,.yml,application/json,application/yaml,text/yaml"
            placeholder={t("import.upload")}
            variant={disabled ? "disabled" : "primary"}
            setValue={(text) => {
              if (text.trim()) void runImport({ openapi_document: text });
            }}
          />
          <Section flexDirection="row" gap={2} height="auto">
            <InputTypeIn
              aria-label={t("import.url")}
              placeholder={t("import.urlPlaceholder")}
              value={specUrl}
              variant={disabled ? "disabled" : "primary"}
              onChange={(event) => setSpecUrl(event.target.value)}
            />
            <Button
              type="button"
              prominence="secondary"
              disabled={disabled || !specUrl.trim()}
              onClick={() => void runImport({ spec_url: specUrl.trim() })}
            >
              {t("import.submit")}
            </Button>
          </Section>
        </Section>
      </InputVertical>
      <InputVertical
        title={t("baseUrl.title")}
        error={
          showErrors && !draft.baseUrl.trim()
            ? t("baseUrl.required")
            : undefined
        }
      >
        <InputTypeIn
          aria-label={t("baseUrl.title")}
          placeholder={t("baseUrl.placeholder")}
          value={draft.baseUrl}
          variant={disabled ? "disabled" : "primary"}
          onChange={(event) =>
            onChange({ ...draft, baseUrl: event.target.value })
          }
        />
      </InputVertical>
      <EndpointLinesField
        value={draft.endpoints}
        onChange={(endpoints) => onChange({ ...draft, endpoints })}
        lineErrors={lineErrors}
        showErrors={showErrors}
        disabled={disabled}
      />
    </>
  );
}

interface EndpointLinesFieldProps {
  value: string;
  onChange: (value: string) => void;
  lineErrors: EndpointLineError[];
  showErrors: boolean;
  disabled: boolean;
}

/** One endpoint per line, with the server's error for each line. */
export function EndpointLinesField({
  value,
  onChange,
  lineErrors,
  showErrors,
  disabled,
}: EndpointLinesFieldProps) {
  const t = useTranslations("admin.integrations.add.rest");
  const lines = value.split("\n");
  return (
    <InputVertical
      title={t("endpoints.title")}
      description={t("endpoints.description")}
      error={
        showErrors && !lines.some((line) => line.trim())
          ? t("endpoints.required")
          : undefined
      }
    >
      <Section gap={1} alignItems="stretch" height="auto">
        <InputTextArea
          aria-label={t("endpoints.title")}
          placeholder={t("endpoints.placeholder")}
          value={value}
          rows={8}
          variant={disabled ? "disabled" : "primary"}
          onChange={(event) => onChange(event.target.value)}
        />
        {lineErrors.map((error) => (
          <InputErrorText key={`${error.line}-${error.message}`}>
            {t("endpoints.lineError", {
              line: error.line + 1,
              text: lines[error.line] ?? "",
              message: error.message,
            })}
          </InputErrorText>
        ))}
      </Section>
    </InputVertical>
  );
}
