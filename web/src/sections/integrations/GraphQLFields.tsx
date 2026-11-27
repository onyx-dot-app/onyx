"use client";

import { useRef, useState } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  InputSingleUpload,
  InputTextArea,
  InputTypeIn,
} from "@opal/components";
import { SvgX } from "@opal/icons";
import { InputVertical, Section, toast } from "@opal/layouts";
import { introspectGraphQL } from "@/lib/integrations/svc";
import type { GraphQLConfig } from "@/lib/integrations/types";
import {
  SPEC_MAX_SIZE_KB,
  specTextTooLarge,
} from "@/sections/integrations/detectApi";

interface GraphQLFieldsProps {
  draft: GraphQLConfig;
  onChange: (draft: GraphQLConfig) => void;
  showErrors: boolean;
  /** Also true while introspection runs; the parent holds that state. */
  disabled: boolean;
  onLoadingChange: (loading: boolean) => void;
  /** A refused schema or a failed load; the parent blocks Save while it is set. */
  importError: string | null;
  onImportErrorChange: (importError: string | null) => void;
}

/** The GraphQL form: an endpoint URL and a schema in SDL. */
export default function GraphQLFields({
  draft,
  onChange,
  showErrors,
  disabled,
  onLoadingChange,
  importError,
  onImportErrorChange,
}: GraphQLFieldsProps) {
  const t = useTranslations("admin.integrations.add.graphql");
  const tAdd = useTranslations("admin.integrations.add");
  // True from a file pick until its text arrives, so an empty file is told
  // apart from the clear button, which also reports "".
  const readingFileRef = useRef(false);
  // An upload over the limit; `importError` shows its error until it is removed.
  const [rejected, setRejected] = useState(false);

  /** Applies the schema when it fits; false when it is over the limit. */
  function setSchema(text: string): boolean {
    setRejected(false);
    const over = specTextTooLarge(text);
    onImportErrorChange(over ? tAdd("api.tooLarge") : null);
    if (!over) onChange({ ...draft, graphql_schema: text });
    return !over;
  }

  async function introspect() {
    setRejected(false);
    onLoadingChange(true);
    try {
      const view = await introspectGraphQL(draft.endpoint_url);
      if (setSchema(view.graphql_schema)) toast.success(t("introspect.done"));
    } catch (error) {
      onImportErrorChange(
        error instanceof Error ? error.message : t("introspect.failed")
      );
    } finally {
      onLoadingChange(false);
    }
  }

  return (
    <>
      <InputVertical
        title={t("endpointUrl.title")}
        error={
          showErrors && !draft.endpoint_url.trim()
            ? t("endpointUrl.required")
            : undefined
        }
      >
        <Section flexDirection="row" gap={2} height="auto">
          <InputTypeIn
            aria-label={t("endpointUrl.title")}
            placeholder={t("endpointUrl.placeholder")}
            value={draft.endpoint_url}
            variant={disabled ? "disabled" : "primary"}
            onChange={(event) => {
              // An edit discards a failed load; the schema stays as it was.
              setRejected(false);
              onImportErrorChange(null);
              onChange({ ...draft, endpoint_url: event.target.value });
            }}
          />
          <Button
            type="button"
            prominence="secondary"
            disabled={disabled || !draft.endpoint_url.trim()}
            onClick={() => void introspect()}
          >
            {t("introspect.submit")}
          </Button>
        </Section>
      </InputVertical>
      <InputVertical
        title={t("schema.title")}
        description={t("schema.description")}
        error={
          importError ??
          (showErrors && !draft.graphql_schema.trim()
            ? t("schema.required")
            : undefined)
        }
      >
        <Section gap={2} alignItems="stretch" height="auto">
          <Section flexDirection="row" gap={1} height="auto">
            <InputSingleUpload
              accept=".graphql,.graphqls,.gql,text/plain"
              placeholder={t("schema.upload")}
              variant={disabled ? "disabled" : "primary"}
              maxSizeKb={SPEC_MAX_SIZE_KB}
              onFileSizeExceeded={() => {
                setRejected(true);
                onImportErrorChange(tAdd("api.tooLarge"));
              }}
              onReadingChange={(reading) => {
                if (reading) readingFileRef.current = true;
                onLoadingChange(reading);
              }}
              setValue={(text) => {
                const fromFile = readingFileRef.current;
                readingFileRef.current = false;
                // A blank or unreadable file or a blank paste is a failed
                // load; a clear keeps the schema.
                const failed = !text.trim() && (fromFile || text !== "");
                setRejected(failed);
                if (text.trim()) setSchema(text);
                else onImportErrorChange(failed ? t("schema.required") : null);
              }}
            />
            {/* A refused or unreadable file is never attached, so the control
                has no clear button; this one keeps the current schema. */}
            {rejected && importError !== null && (
              <Button
                type="button"
                size="sm"
                prominence="tertiary"
                icon={SvgX}
                aria-label={tAdd("api.upload.remove")}
                onClick={() => {
                  setRejected(false);
                  onImportErrorChange(null);
                }}
              />
            )}
          </Section>
          <InputTextArea
            aria-label={t("schema.title")}
            value={draft.graphql_schema}
            rows={12}
            variant={disabled ? "disabled" : "primary"}
            onChange={(event) => setSchema(event.target.value)}
          />
        </Section>
      </InputVertical>
    </>
  );
}
