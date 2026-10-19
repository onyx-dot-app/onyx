"use client";

import { useEffect } from "react";
import { useTranslations } from "next-intl";
import { useFormikContext } from "formik";
import {
  Button,
  Card,
  CopyButton,
  Divider,
  EmptyMessageCard,
} from "@opal/components";
import {
  Content,
  ContentAction,
  InputPadder,
  InputVertical,
} from "@opal/layouts";
import { Hoverable } from "@opal/core";
import { CardLoaders } from "@opal/loaders";
import { SvgActions, SvgBracketCurly, SvgInfo } from "@opal/icons";
import { markdown } from "@opal/utils";
import InputTextAreaField from "@/refresh-components/form/InputTextAreaField";
import { DOCS_ADMINS_PATH } from "@/lib/constants";
import { getActionIcon } from "@/lib/tools/utils";
import { OpenAPIMethodPath } from "@/lib/plugins/components";
import {
  openApiMethodColoredIcon,
  sortByOpenApiMethod,
} from "@/lib/plugins/openapi/methods";
import { formatOpenApiSchema } from "@/lib/plugins/openapi/schema";
import type { OpenApiSchemaCheck } from "@/lib/plugins/openapi/hooks";
import type { OpenAPIPluginFormValues } from "@/lib/plugins/openapi/types";

interface OpenAPISchemaFieldsProps {
  schema: OpenApiSchemaCheck;
  disabled: boolean;
}

/**
 * The OpenAPI modal's Schema tab: the schema field, then the API and the
 * actions it defines, previewed live from the text.
 */
export default function OpenAPISchemaFields({
  schema,
  disabled,
}: OpenAPISchemaFieldsProps) {
  const t = useTranslations("actions");
  const { values, errors, setFieldValue, setFieldError } =
    useFormikContext<OpenAPIPluginFormValues>();
  const { checked } = schema;

  // The server's verdict on the schema shows as the field's error.
  useEffect(() => {
    if (schema.error && errors.definition !== schema.error)
      setFieldError("definition", schema.error);
  }, [schema.error, errors.definition, setFieldError]);

  function format() {
    if (!values.definition.trim()) return;
    try {
      void setFieldValue("definition", formatOpenApiSchema(values.definition));
    } catch {
      setFieldError("definition", t("addOpenApiModal.definition.invalidJson"));
    }
  }

  const info = checked?.definition.info;
  const url = checked?.definition.servers?.[0]?.url;
  const PluginIcon = getActionIcon(url ?? "", info?.title ?? "");

  return (
    <div className="flex flex-col">
      <InputPadder>
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
                        disabled={disabled}
                        aria-label={t("addOpenApiModal.formatButton.tooltip")}
                        tooltip={t("addOpenApiModal.formatButton.tooltip")}
                        onClick={format}
                      />
                    </div>
                  </Hoverable.Item>
                </div>
              )}
              <InputTextAreaField
                name="definition"
                font="main-ui-mono"
                variant={disabled ? "disabled" : undefined}
                rows={8}
                placeholder={t("addOpenApiModal.definition.placeholder")}
              />
            </div>
          </Hoverable.Root>
        </InputVertical>
      </InputPadder>

      {schema.pending ? (
        <>
          <Divider paddingParallel={2} paddingPerpendicular={2} />
          <div role="status" aria-label={t("addOpenApiModal.preview.checking")}>
            <CardLoaders />
          </div>
        </>
      ) : checked && checked.methods.length > 0 ? (
        <>
          <Divider paddingParallel={2} paddingPerpendicular={2} />
          {info?.title && (
            <InputPadder>
              <Content
                sizePreset="main-ui"
                variant="section"
                icon={PluginIcon}
                title={info.title}
                description={info.description}
              />
            </InputPadder>
          )}
          {url && (
            <InputPadder>
              <Content
                sizePreset="main-ui"
                variant="section"
                icon={SvgInfo}
                title={url}
                description={t("addOpenApiModal.preview.urlDescription")}
              />
            </InputPadder>
          )}
          <Divider paddingParallel={2} paddingPerpendicular={2} />
          <div className="flex flex-col gap-1">
            {sortByOpenApiMethod(checked.methods).map((method) => (
              <Card
                key={`${method.method}-${method.path}-${method.name}`}
                padding={2}
                border="solid"
              >
                <ContentAction
                  sizePreset="main-ui"
                  variant="section"
                  padding={0}
                  rightChildren={<OpenAPIMethodPath method={method} />}
                  icon={openApiMethodColoredIcon(method.method)}
                  title={method.name}
                  description={
                    method.summary || t("addOpenApiModal.method.noSummary")
                  }
                />
              </Card>
            ))}
          </div>
        </>
      ) : (
        checked && (
          <EmptyMessageCard
            sizePreset="main-ui"
            title={t("addOpenApiModal.empty.title")}
            icon={SvgActions}
            description={t("addOpenApiModal.empty.description")}
          />
        )
      )}
    </div>
  );
}
