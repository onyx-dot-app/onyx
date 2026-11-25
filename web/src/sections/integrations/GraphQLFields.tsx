"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  InputSingleUpload,
  InputTextArea,
  InputTypeIn,
} from "@opal/components";
import { InputVertical, Section, toast } from "@opal/layouts";
import { introspectGraphQL } from "@/lib/integrations/svc";
import type { GraphQLConfig } from "@/lib/integrations/types";

interface GraphQLFieldsProps {
  draft: GraphQLConfig;
  onChange: (draft: GraphQLConfig) => void;
  showErrors: boolean;
  disabled: boolean;
}

/** The GraphQL form: an endpoint URL and a schema in SDL. */
export default function GraphQLFields({
  draft,
  onChange,
  showErrors,
  disabled,
}: GraphQLFieldsProps) {
  const t = useTranslations("admin.integrations.add.graphql");
  const [loading, setLoading] = useState(false);
  const busy = disabled || loading;

  async function introspect() {
    setLoading(true);
    try {
      const view = await introspectGraphQL(draft.endpoint_url);
      onChange({ ...draft, graphql_schema: view.graphql_schema });
      toast.success(t("introspect.done"));
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : t("introspect.failed")
      );
    } finally {
      setLoading(false);
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
            variant={busy ? "disabled" : "primary"}
            onChange={(event) =>
              onChange({ ...draft, endpoint_url: event.target.value })
            }
          />
          <Button
            type="button"
            prominence="secondary"
            disabled={busy || !draft.endpoint_url.trim()}
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
          showErrors && !draft.graphql_schema.trim()
            ? t("schema.required")
            : undefined
        }
      >
        <Section gap={2} alignItems="stretch" height="auto">
          <InputSingleUpload
            accept=".graphql,.graphqls,.gql,text/plain"
            placeholder={t("schema.upload")}
            variant={busy ? "disabled" : "primary"}
            setValue={(text) => {
              if (text.trim()) onChange({ ...draft, graphql_schema: text });
            }}
          />
          <InputTextArea
            aria-label={t("schema.title")}
            value={draft.graphql_schema}
            rows={12}
            variant={busy ? "disabled" : "primary"}
            onChange={(event) =>
              onChange({ ...draft, graphql_schema: event.target.value })
            }
          />
        </Section>
      </InputVertical>
    </>
  );
}
