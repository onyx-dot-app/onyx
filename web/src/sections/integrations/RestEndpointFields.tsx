"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  Collapsible,
  InputSingleUpload,
  InputTextArea,
  InputTypeIn,
  Text,
} from "@opal/components";
import { InputErrorText, InputVertical, Section, toast } from "@opal/layouts";
import { importOpenApiSpec } from "@/lib/integrations/svc";
import type {
  EndpointLineError,
  OpenApiConfigView,
} from "@/lib/integrations/types";
import {
  SPEC_MAX_SIZE_KB,
  restBaseUrl,
  specTextTooLarge,
  specBaseUrl,
} from "@/sections/integrations/detectApi";

/** The REST endpoint form: a base URL and one endpoint per line. */
export interface RestDraft {
  /** The imported or stored document that the lines edit; null for none. */
  document: string | null;
  baseUrl: string;
  endpoints: string;
}

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
  /** A refused or failed import; the parent blocks Save while it is set. */
  importError: string | null;
  onImportErrorChange: (importError: string | null) => void;
}

export default function RestEndpointFields({
  draft,
  onChange,
  lineErrors,
  showErrors,
  disabled,
  onImportingChange,
  importError,
  onImportErrorChange,
}: RestEndpointFieldsProps) {
  const t = useTranslations("admin.integrations.add.rest");
  const tAdd = useTranslations("admin.integrations.add");
  const [specUrl, setSpecUrl] = useState("");
  // Save drops the actions of these operations, so show them before Save.
  const [skipped, setSkipped] = useState<string[]>([]);

  async function runImport(
    body: { openapi_document: string } | { spec_url: string }
  ) {
    onImportingChange(true);
    try {
      const view = await importOpenApiSpec(body);
      const specUrl = "spec_url" in body ? body.spec_url : null;
      // A file gives no URL to resolve a relative server against, and a spec
      // with no single server gives no URL, so the Base URL stays.
      onChange({
        ...restDraftFrom(view),
        baseUrl:
          specBaseUrl(view.base_url, view.base_url.trim() ? specUrl : null) ??
          (draft.baseUrl.trim() || view.base_url),
      });
      setSkipped(view.skipped);
      onImportErrorChange(null);
      toast.success(t("import.done", { count: view.endpoints.length }));
    } catch (error) {
      onImportErrorChange(
        error instanceof Error ? error.message : t("import.failed")
      );
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
        error={importError ?? undefined}
      >
        <Section gap={2} alignItems="stretch" height="auto">
          <InputSingleUpload
            accept=".json,.yaml,.yml,application/json,application/yaml,text/yaml"
            placeholder={t("import.upload")}
            variant={disabled ? "disabled" : "primary"}
            maxSizeKb={SPEC_MAX_SIZE_KB}
            onFileSizeExceeded={() => onImportErrorChange(tAdd("api.tooLarge"))}
            // Called before setValue, which may start an import.
            onReadingChange={onImportingChange}
            setValue={(text) => {
              const over = specTextTooLarge(text);
              onImportErrorChange(over ? tAdd("api.tooLarge") : null);
              if (!over && text.trim())
                void runImport({ openapi_document: text });
            }}
          />
          <Section flexDirection="row" gap={2} height="auto">
            <InputTypeIn
              aria-label={t("import.url")}
              placeholder={t("import.urlPlaceholder")}
              value={specUrl}
              variant={disabled ? "disabled" : "primary"}
              onChange={(event) => {
                setSpecUrl(event.target.value);
                if (!event.target.value.trim()) onImportErrorChange(null);
              }}
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
          <SkippedOperations lines={skipped} />
        </Section>
      </InputVertical>
      <InputVertical
        title={t("baseUrl.title")}
        error={
          showErrors && !restBaseUrl(draft.baseUrl)
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

/** The spec operations that an import could not turn into endpoints. */
export function SkippedOperations({ lines }: { lines: string[] }) {
  const t = useTranslations("admin.integrations.add");
  if (lines.length === 0) return null;
  return (
    <Collapsible title={t("detected.skippedTitle")} defaultOpen={false}>
      <Section gap={1} alignItems="stretch" height="auto">
        {lines.map((line) => (
          <Text key={line} as="p" font="secondary-body" color="text-03">
            {line}
          </Text>
        ))}
      </Section>
    </Collapsible>
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
