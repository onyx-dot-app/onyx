"use client";
import { useTranslations } from "next-intl";
import { useFormikContext } from "formik";
import type { MCPAuthFormValues } from "@/sections/actions/modals/types";
import { FormField } from "@/refresh-components/form/FormField";
import { Section } from "@opal/layouts";
import { InputPasswordTypeIn, InputSingleSelect } from "@opal/components";
import { MCPAuthenticationPerformer } from "@/lib/mcp/types";
import { PerUserAuthConfig } from "@/sections/actions/PerUserAuthConfig";
interface MCPApiTokenFieldsProps {
  onSettingsChange: () => void;
  disabled?: boolean;
}
export function MCPApiTokenFields({
  onSettingsChange,
  disabled = false,
}: MCPApiTokenFieldsProps) {
  const t = useTranslations("actions");
  const { values, setValues, setFieldValue, errors, touched, handleChange } =
    useFormikContext<MCPAuthFormValues>();
  return (
    <Section alignItems="stretch" height="auto" gap={4}>
      <FormField name="auth_performer">
        <FormField.Label>
          {t("mcpAuthModal.authPerformer.label")}
        </FormField.Label>
        <FormField.Control asChild>
          <InputSingleSelect
            disabled={disabled}
            value={
              values.auth_performer === MCPAuthenticationPerformer.ADMIN
                ? "admin"
                : "per-user"
            }
            defaultOption="per-user"
            placeholder={t("mcpAuthModal.authPerformer.label")}
            options={[
              {
                value: "per-user",
                title: t("mcpAuthModal.apiKeyTabs.perUser.label"),
              },
              {
                value: "admin",
                title: t("mcpAuthModal.apiKeyTabs.admin.label"),
              },
            ]}
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
          />
        </FormField.Control>
      </FormField>
      {values.auth_performer === MCPAuthenticationPerformer.PER_USER ? (
        <PerUserAuthConfig
          section="credentials"
          values={values}
          setFieldValue={setFieldValue}
        />
      ) : (
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
      )}
    </Section>
  );
}
