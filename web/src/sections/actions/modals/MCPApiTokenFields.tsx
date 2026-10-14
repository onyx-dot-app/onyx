"use client";
import { useTranslations } from "next-intl";
import { useFormikContext } from "formik";
import type { MCPAuthFormValues } from "@/sections/actions/modals/types";
import { FormField } from "@/refresh-components/form/FormField";
import { Section } from "@opal/layouts";
import { InputPasswordTypeIn, Tabs } from "@opal/components";
import { MCPAuthenticationPerformer } from "@/lib/mcp/types";
import { PerUserAuthConfig } from "@/sections/actions/PerUserAuthConfig";
interface MCPApiTokenFieldsProps {
  onSettingsChange: () => void;
}
export function MCPApiTokenFields({
  onSettingsChange,
}: MCPApiTokenFieldsProps) {
  const t = useTranslations("actions");
  const { values, setValues, setFieldValue, errors, touched, handleChange } =
    useFormikContext<MCPAuthFormValues>();
  return (
    <Tabs
      gap={5}
      value={
        values.auth_performer === MCPAuthenticationPerformer.ADMIN
          ? "admin"
          : "per-user"
      }
      onValueChange={(value) => {
        onSettingsChange();
        const performer =
          value === "per-user"
            ? MCPAuthenticationPerformer.PER_USER
            : MCPAuthenticationPerformer.ADMIN;
        if (performer !== values.auth_performer) {
          setValues({
            ...values,
            auth_performer: performer,
            api_token: "",
            user_credentials: {},
          });
        }
      }}
    >
      <Tabs.List>
        <Tabs.Trigger value="per-user">
          {t("mcpAuthModal.apiKeyTabs.perUser.label")}
        </Tabs.Trigger>
        <Tabs.Trigger value="admin">
          {t("mcpAuthModal.apiKeyTabs.admin.label")}
        </Tabs.Trigger>
      </Tabs.List>

      {/* Per-user Tab Content */}
      <Tabs.Content value="per-user">
        <PerUserAuthConfig
          section="credentials"
          values={values}
          setFieldValue={setFieldValue}
        />
      </Tabs.Content>

      {/* Admin Tab Content */}
      <Tabs.Content value="admin">
        <div className="flex flex-col gap-4">
          <FormField
            name="api_token"
            state={
              errors.api_token && touched.api_token
                ? "error"
                : touched.api_token
                  ? "success"
                  : "idle"
            }
          >
            <FormField.Label>
              {t("mcpAuthModal.sharedApiKey.label")}
            </FormField.Label>
            <FormField.Description>
              {t("mcpAuthModal.sharedApiKey.description")}
            </FormField.Description>
            <FormField.Control asChild>
              <InputPasswordTypeIn
                name="api_token"
                value={values.api_token}
                onChange={handleChange}
                placeholder={t("mcpAuthModal.sharedApiKey.placeholder")}
              />
            </FormField.Control>
            <FormField.Message
              messages={{
                error: errors.api_token,
              }}
            />
          </FormField>
          <PerUserAuthConfig
            section="credentials"
            values={values}
            setFieldValue={setFieldValue}
            mode="shared"
          />
        </div>
      </Tabs.Content>
    </Tabs>
  );
}
