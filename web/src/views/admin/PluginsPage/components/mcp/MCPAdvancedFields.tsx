"use client";
import { useTranslations } from "next-intl";
import { useFormikContext } from "formik";
import type { MCPAuthFormValues } from "@/views/admin/PluginsPage/components/mcp/types";
import { FormField } from "@/refresh-components/form/FormField";
import { Section } from "@opal/layouts";
import { Collapsible, Divider, InputSingleSelect } from "@opal/components";
import {
  MCPAuthenticationType,
  MCPAuthenticationPerformer,
  MCPTransportType,
} from "@/lib/mcp/types";
import { PerUserAuthConfig } from "@/views/admin/PluginsPage/components/mcp/PerUserAuthConfig";
interface MCPAdvancedFieldsProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}
export function MCPAdvancedFields({
  open,
  onOpenChange,
}: MCPAdvancedFieldsProps) {
  const t = useTranslations("actions");
  const { values, setFieldValue } = useFormikContext<MCPAuthFormValues>();
  return (
    <div className="border-t border-border-01 pt-5">
      <Collapsible
        open={open}
        onOpenChange={onOpenChange}
        title={t("mcpAuthModal.advancedSettings.title")}
      >
        <Section alignItems="stretch" height="auto" gap={6} padding={0}>
          <PerUserAuthConfig
            key={values.auth_type + values.auth_performer}
            section="headers"
            values={values}
            setFieldValue={setFieldValue}
            mode={
              values.auth_type === MCPAuthenticationType.API_TOKEN &&
              values.auth_performer === MCPAuthenticationPerformer.ADMIN
                ? "shared"
                : "per-user"
            }
          />
          <Divider paddingPerpendicular={0} />
          <FormField name="transport">
            <FormField.Label>
              {t("mcpAuthModal.transport.label")}
            </FormField.Label>
            <FormField.Control asChild>
              <InputSingleSelect
                value={values.transport}
                onValueChange={(value) => setFieldValue("transport", value)}
                defaultOption={MCPTransportType.STREAMABLE_HTTP}
                placeholder={t("mcpAuthModal.transport.label")}
                options={[
                  {
                    value: MCPTransportType.STREAMABLE_HTTP,
                    title: t("mcpAuthModal.transport.httpLabel"),
                  },
                  {
                    value: MCPTransportType.SSE,
                    title: t("mcpAuthModal.transport.sseLabel"),
                  },
                ]}
              />
            </FormField.Control>
            <FormField.Description>
              {t("mcpAuthModal.transport.description")}
            </FormField.Description>
          </FormField>
        </Section>
      </Collapsible>
    </div>
  );
}
