"use client";

import { useState } from "react";
import { Form, Formik } from "formik";
import * as Yup from "yup";
import { Button, Text } from "@opal/components";
import { SvgCopy, SvgSimpleLoader } from "@opal/icons";
import { InputVertical, toast } from "@opal/layouts";
import { cn } from "@opal/utils";
import type {
  SSOProviderCreateRequest,
  SSOProviderResponse,
  SSOProviderType,
  SSOProviderUpdateRequest,
} from "@/lib/sso/interfaces";
import { createSSOProvider, updateSSOProvider } from "@/lib/sso/svc";
import {
  CONFIG_FIELDS_BY_TYPE,
  copyRedirectUri,
  CREATABLE_SSO_PROVIDER_TYPES,
  SSO_PROVIDER_DETAILS,
  type SSOConfigField,
} from "@/lib/sso/utils";
import PasswordInputTypeInField from "@/refresh-components/form/PasswordInputTypeInField";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import InputTextAreaField from "@/refresh-components/form/InputTextAreaField";
import UnlabeledCheckboxField from "@/refresh-components/form/CheckboxField";
import InputChipField, {
  type ChipItem,
} from "@/refresh-components/inputs/InputChipField";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import { Modal } from "@opal/components";
import { useModalClose } from "@opal/components";

export interface SSOProviderModalProps {
  provider: SSOProviderResponse | null;
  onSaved: () => Promise<unknown>;
}

// Config values are keyed dynamically (config.<field name>), so they live in a
// nested map Formik addresses by path while the fixed fields stay typed.
interface SSOProviderFormValues {
  provider_type: SSOProviderType;
  name: string;
  display_name: string;
  config: Record<string, string>;
  allowed_email_domains: string[];
  allow_email_link: boolean;
}

// Every config key across all provider types (deduped by name, since provider
// types share field constants), so switching type in create mode never lands
// on an uncontrolled input.
const ALL_CONFIG_FIELDS: SSOConfigField[] = Array.from(
  new Map(
    CREATABLE_SSO_PROVIDER_TYPES.flatMap(
      (type) => CONFIG_FIELDS_BY_TYPE[type]
    ).map((field) => [field.name, field])
  ).values()
);

function configSchemaForType(fields: SSOConfigField[]) {
  const shape: Record<string, Yup.StringSchema> = {};
  for (const field of fields) {
    shape[field.name] = field.optional
      ? Yup.string().optional()
      : Yup.string().required(`${field.label} is required`);
  }
  return Yup.object(shape);
}

const CONFIG_SCHEMA_BY_TYPE = Object.fromEntries(
  CREATABLE_SSO_PROVIDER_TYPES.map((type) => [
    type,
    configSchemaForType(CONFIG_FIELDS_BY_TYPE[type]),
  ])
);

const SSO_VALIDATION_SCHEMA = Yup.object({
  provider_type: Yup.string()
    .oneOf(CREATABLE_SSO_PROVIDER_TYPES)
    .required("Provider type is required"),
  name: Yup.string()
    .required("Name is required")
    .matches(
      /^[a-z0-9-]+$/,
      "Use lowercase letters, numbers, and hyphens only"
    ),
  display_name: Yup.string().required("Display name is required"),
  // The whole config schema switches on the sibling provider_type (a when()
  // nested inside the config object cannot see parent keys, so per-field
  // conditions would silently never require anything). On edit the masked
  // value prefills, so "required" passes without re-entry.
  config: Yup.object().when(
    "provider_type",
    ([type], schema) => CONFIG_SCHEMA_BY_TYPE[type as string] ?? schema
  ),
  allowed_email_domains: Yup.array().of(Yup.string()).optional(),
  // Mirrors the backend: linking existing accounts by email is only allowed
  // when the provider is scoped to specific domains it is authoritative for.
  allow_email_link: Yup.boolean().test(
    "requires-domains",
    "Add at least one allowed email domain to enable account linking",
    function (value) {
      if (!value) {
        return true;
      }
      const domains = this.parent.allowed_email_domains as string[] | undefined;
      return Array.isArray(domains) && domains.length > 0;
    }
  ),
});

// The backend masks every config string on read and restores any value sent
// back unchanged, so the form sends its current values as-is. Blank optional
// keys are omitted rather than sent as empty strings.
function buildConfig(
  providerType: SSOProviderType,
  values: SSOProviderFormValues
): Record<string, string> {
  const config: Record<string, string> = {};
  for (const field of CONFIG_FIELDS_BY_TYPE[providerType]) {
    const raw = values.config[field.name] ?? "";
    const value = field.kind === "password" ? raw : raw.trim();
    if (field.optional && !value) {
      continue;
    }
    config[field.name] = value;
  }
  return config;
}

function initialConfig(config: Record<string, string>): Record<string, string> {
  const initial: Record<string, string> = {};
  for (const field of ALL_CONFIG_FIELDS) {
    initial[field.name] = config[field.name] ?? "";
  }
  return initial;
}

function ConfigInput({
  field,
  isEditing,
}: {
  field: SSOConfigField;
  isEditing: boolean;
}) {
  const name = `config.${field.name}`;
  if (field.kind === "textarea") {
    return <InputTextAreaField name={name} placeholder={field.placeholder} />;
  }
  if (field.kind === "password") {
    return (
      <PasswordInputTypeInField
        name={name}
        placeholder={field.placeholder}
        isNonRevealable={isEditing}
      />
    );
  }
  return <InputTypeInField name={name} placeholder={field.placeholder} />;
}

export function SSOProviderModal({ provider, onSaved }: SSOProviderModalProps) {
  const onClose = useModalClose();
  const isEditing = provider !== null;
  const [domainInput, setDomainInput] = useState("");

  const initialValues: SSOProviderFormValues = {
    provider_type: provider?.provider_type ?? "GOOGLE_OAUTH",
    name: provider?.name ?? "",
    display_name: provider?.display_name ?? "",
    config: initialConfig(provider?.config ?? {}),
    allowed_email_domains: provider?.allowed_email_domains ?? [],
    allow_email_link: provider?.allow_email_link ?? false,
  };

  async function handleSubmit(
    values: SSOProviderFormValues,
    { setSubmitting }: { setSubmitting: (isSubmitting: boolean) => void }
  ) {
    const providerType = values.provider_type;
    const config = buildConfig(providerType, values);
    try {
      if (!isEditing) {
        const request: SSOProviderCreateRequest = {
          name: values.name.trim(),
          display_name: values.display_name.trim(),
          provider_type: providerType,
          config,
          allowed_email_domains: values.allowed_email_domains,
          allow_email_link: values.allow_email_link,
        };
        await createSSOProvider(request);
        toast.success("SSO provider created");
      } else {
        const request: SSOProviderUpdateRequest = {
          display_name: values.display_name.trim(),
          allowed_email_domains: values.allowed_email_domains,
          config,
          allow_email_link: values.allow_email_link,
        };
        await updateSSOProvider(provider.id, request);
        toast.success("SSO provider updated");
      }
      await onSaved();
      onClose?.();
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Unexpected error occurred."
      );
    } finally {
      setSubmitting(false);
    }
  }

  const redirectLabel =
    provider?.provider_type === "SAML" ? "ACS (Reply) URL" : "Redirect URI";

  return (
    <Modal open onOpenChange={onClose}>
      <Modal.Content width="md" height="full" preventAccidentalClose>
        <Formik<SSOProviderFormValues>
          initialValues={initialValues}
          validationSchema={SSO_VALIDATION_SCHEMA}
          onSubmit={handleSubmit}
          enableReinitialize
        >
          {({
            values,
            setFieldValue,
            errors,
            touched,
            isSubmitting,
            dirty,
            isValid,
          }) => {
            const providerType = values.provider_type;
            const providerTypeIcon = SSO_PROVIDER_DETAILS[providerType].icon;
            const domainChips: ChipItem[] = values.allowed_email_domains.map(
              (domain) => ({ id: domain, label: domain })
            );

            return (
              // flex-col fills the fixed-height Content so Modal.Body scrolls
              // while the header and footer stay pinned.
              <Form className="flex min-h-0 flex-1 flex-col">
                <Modal.Header
                  icon={providerTypeIcon}
                  title={
                    isEditing
                      ? `Edit ${provider.display_name}`
                      : "Add SSO Provider"
                  }
                  description={
                    isEditing
                      ? "Update how this provider signs users in."
                      : "Add a Google, OIDC, or SAML provider for sign-in."
                  }
                  onClose={onClose}
                />

                <Modal.Body>
                  <InputVertical
                    title="Provider Type"
                    description="The protocol this provider authenticates with."
                    withLabel="provider_type"
                  >
                    <InputSelect
                      value={values.provider_type}
                      onValueChange={(value) => {
                        void setFieldValue("provider_type", value);
                      }}
                      disabled={isEditing}
                      error={Boolean(
                        touched.provider_type && errors.provider_type
                      )}
                    >
                      <InputSelect.Trigger placeholder="Select a provider type" />
                      <InputSelect.Content>
                        {CREATABLE_SSO_PROVIDER_TYPES.map((type) => {
                          const detail = SSO_PROVIDER_DETAILS[type];
                          return (
                            <InputSelect.Item
                              key={type}
                              value={type}
                              icon={detail.icon}
                              description={detail.description}
                              wrapDescription
                            >
                              {detail.label}
                            </InputSelect.Item>
                          );
                        })}
                      </InputSelect.Content>
                    </InputSelect>
                  </InputVertical>

                  <InputVertical
                    title="Name"
                    description="Unique lowercase slug used in the login URL. Cannot be changed later."
                    withLabel="name"
                  >
                    <InputTypeInField
                      name="name"
                      placeholder="company-a"
                      variant={isEditing ? "disabled" : undefined}
                    />
                  </InputVertical>

                  <InputVertical
                    title="Display Name"
                    description="Label shown on the sign-in button."
                    withLabel="display_name"
                  >
                    <InputTypeInField
                      name="display_name"
                      placeholder="Company A"
                    />
                  </InputVertical>

                  {CONFIG_FIELDS_BY_TYPE[providerType].map((field) => (
                    <InputVertical
                      key={field.name}
                      title={
                        field.optional
                          ? `${field.label} (Optional)`
                          : field.label
                      }
                      description={field.description}
                      withLabel={`config.${field.name}`}
                    >
                      <ConfigInput field={field} isEditing={isEditing} />
                    </InputVertical>
                  ))}

                  <InputVertical
                    title="Allowed Email Domains (Optional)"
                    description="Only emails in these domains may sign in through this provider. Empty allows any."
                    withLabel
                  >
                    <InputChipField
                      chips={domainChips}
                      onRemoveChip={(id) => {
                        void setFieldValue(
                          "allowed_email_domains",
                          values.allowed_email_domains.filter(
                            (domain) => domain !== id
                          )
                        );
                      }}
                      onAdd={(value) => {
                        const trimmed = value.trim().toLowerCase();
                        if (
                          trimmed &&
                          !values.allowed_email_domains.includes(trimmed)
                        ) {
                          void setFieldValue("allowed_email_domains", [
                            ...values.allowed_email_domains,
                            trimmed,
                          ]);
                        }
                        setDomainInput("");
                      }}
                      value={domainInput}
                      onChange={setDomainInput}
                      placeholder="Add a domain (e.g. onyx.app)"
                    />
                  </InputVertical>

                  <InputVertical
                    title="Link Existing Accounts by Email"
                    description="Let a user whose account was created another way (a different provider, SAML, or password) sign in through this provider. Requires allowed email domains, since the provider can only claim accounts in domains it is authoritative for."
                    withLabel="allow_email_link"
                  >
                    <UnlabeledCheckboxField name="allow_email_link" />
                  </InputVertical>

                  {provider?.redirect_uri && (
                    <InputVertical
                      title={redirectLabel}
                      description="Register this URL in your IdP as the callback."
                      withLabel
                    >
                      <div
                        className={cn(
                          "flex items-start justify-between gap-2 rounded-12 border border-border-03 bg-background-neutral-02 p-3"
                        )}
                      >
                        <Text font="secondary-body" color="text-04" as="p">
                          {provider.redirect_uri}
                        </Text>
                        <Button
                          icon={SvgCopy}
                          prominence="tertiary"
                          size="sm"
                          tooltip={`Copy ${redirectLabel}`}
                          onClick={() => {
                            void copyRedirectUri(provider.redirect_uri);
                          }}
                        />
                      </div>
                    </InputVertical>
                  )}
                </Modal.Body>

                <Modal.Footer>
                  <Button
                    prominence="secondary"
                    type="button"
                    onClick={onClose}
                  >
                    Cancel
                  </Button>
                  <Button
                    type="submit"
                    disabled={isSubmitting || !isValid || !dirty}
                    icon={isSubmitting ? SvgSimpleLoader : undefined}
                  >
                    {isEditing ? "Update" : "Create"}
                  </Button>
                </Modal.Footer>
              </Form>
            );
          }}
        </Formik>
      </Modal.Content>
    </Modal>
  );
}
