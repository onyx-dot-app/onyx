"use client";

import { useState } from "react";
import { Form, Formik } from "formik";
import * as Yup from "yup";
import { Button, Text } from "@opal/components";
import { SvgCopy, SvgSimpleLoader } from "@opal/icons";
import { InputVertical } from "@opal/layouts";
import { cn } from "@opal/utils";
import { toast } from "@/hooks/useToast";
import type {
  SSOProviderCreateRequest,
  SSOProviderResponse,
  SSOProviderType,
  SSOProviderUpdateRequest,
} from "@/lib/sso/interfaces";
import { createSSOProvider, updateSSOProvider } from "@/lib/sso/svc";
import {
  copyRedirectUri,
  CREATABLE_SSO_PROVIDER_TYPES,
  SSO_PROVIDER_DETAILS,
} from "@/lib/sso/utils";
import PasswordInputTypeInField from "@/refresh-components/form/PasswordInputTypeInField";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import InputTextAreaField from "@/refresh-components/form/InputTextAreaField";
import InputChipField, {
  type ChipItem,
} from "@/refresh-components/inputs/InputChipField";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import Modal from "@/refresh-components/Modal";
import { useModalClose } from "@/refresh-components/contexts/ModalContext";

export interface SSOProviderModalProps {
  provider: SSOProviderResponse | null;
  onSaved: () => Promise<unknown>;
}

interface SSOProviderFormValues {
  provider_type: string;
  name: string;
  display_name: string;
  // OIDC / Google
  client_id: string;
  client_secret: string;
  openid_config_url: string;
  // SAML
  idp_entity_id: string;
  idp_sso_url: string;
  idp_x509_cert: string;
  sp_entity_id: string;
  sp_x509_cert: string;
  sp_private_key: string;
  email_attribute: string;
  allowed_email_domains: string[];
}

function configString(config: Record<string, string>, key: string): string {
  return config[key] ?? "";
}

// The backend masks every config string on read and restores any field whose
// value comes back unchanged, so the form sends its current values and lets the
// server round-trip the untouched (masked) ones. Optional keys are omitted when
// blank so they stay null rather than becoming "".
function buildConfig(values: SSOProviderFormValues): Record<string, string> {
  if (values.provider_type === "SAML") {
    const config: Record<string, string> = {
      idp_entity_id: values.idp_entity_id.trim(),
      idp_sso_url: values.idp_sso_url.trim(),
      idp_x509_cert: values.idp_x509_cert.trim(),
      sp_entity_id: values.sp_entity_id.trim(),
    };
    if (values.sp_x509_cert.trim()) {
      config.sp_x509_cert = values.sp_x509_cert.trim();
    }
    if (values.sp_private_key) {
      config.sp_private_key = values.sp_private_key;
    }
    if (values.email_attribute.trim()) {
      config.email_attribute = values.email_attribute.trim();
    }
    return config;
  }

  const config: Record<string, string> = {
    client_id: values.client_id.trim(),
    client_secret: values.client_secret,
  };
  if (values.provider_type === "OIDC") {
    config.openid_config_url = values.openid_config_url.trim();
  }
  return config;
}

export function SSOProviderModal({ provider, onSaved }: SSOProviderModalProps) {
  const onClose = useModalClose();
  const isEditing = provider !== null;
  const config = provider?.config ?? {};
  const [domainInput, setDomainInput] = useState("");

  const initialValues: SSOProviderFormValues = {
    provider_type: provider?.provider_type ?? "GOOGLE_OAUTH",
    name: provider?.name ?? "",
    display_name: provider?.display_name ?? "",
    client_id: configString(config, "client_id"),
    client_secret: configString(config, "client_secret"),
    openid_config_url: configString(config, "openid_config_url"),
    idp_entity_id: configString(config, "idp_entity_id"),
    idp_sso_url: configString(config, "idp_sso_url"),
    idp_x509_cert: configString(config, "idp_x509_cert"),
    sp_entity_id: configString(config, "sp_entity_id"),
    sp_x509_cert: configString(config, "sp_x509_cert"),
    sp_private_key: configString(config, "sp_private_key"),
    email_attribute: configString(config, "email_attribute"),
    allowed_email_domains: provider?.allowed_email_domains ?? [],
  };

  // Required on create only. On edit the stored (masked) value is already
  // present, so leaving a field untouched is allowed and round-trips.
  const requiredOnCreate = isEditing
    ? Yup.string()
    : Yup.string().required("Required");
  const requiredWhenType = (type: SSOProviderType, message: string) =>
    Yup.string().when("provider_type", {
      is: type,
      then: (schema) => (isEditing ? schema : schema.required(message)),
      otherwise: (schema) => schema.optional(),
    });

  const validationSchema = Yup.object({
    provider_type: Yup.string()
      .oneOf(["GOOGLE_OAUTH", "OIDC", "SAML"])
      .required("Provider type is required"),
    name: Yup.string()
      .required("Name is required")
      .matches(
        /^[a-z0-9-]+$/,
        "Use lowercase letters, numbers, and hyphens only"
      ),
    display_name: Yup.string().required("Display name is required"),
    client_id: Yup.string().when("provider_type", {
      is: (type: string) => type !== "SAML",
      then: (schema) => schema.required("Client ID is required"),
      otherwise: (schema) => schema.optional(),
    }),
    client_secret: Yup.string().when("provider_type", {
      is: (type: string) => type !== "SAML",
      then: () => requiredOnCreate,
      otherwise: (schema) => schema.optional(),
    }),
    openid_config_url: requiredWhenType(
      "OIDC",
      "OpenID configuration URL is required"
    ),
    idp_entity_id: requiredWhenType("SAML", "IdP entity ID is required"),
    idp_sso_url: requiredWhenType("SAML", "IdP SSO URL is required"),
    idp_x509_cert: requiredWhenType("SAML", "IdP certificate is required"),
    sp_entity_id: requiredWhenType("SAML", "SP entity ID is required"),
    allowed_email_domains: Yup.array().of(Yup.string()).optional(),
  });

  async function handleSubmit(
    values: SSOProviderFormValues,
    { setSubmitting }: { setSubmitting: (isSubmitting: boolean) => void }
  ) {
    const providerConfig = buildConfig(values);
    try {
      if (!isEditing) {
        const request: SSOProviderCreateRequest = {
          name: values.name.trim(),
          display_name: values.display_name.trim(),
          provider_type: values.provider_type as SSOProviderType,
          config: providerConfig,
          allowed_email_domains: values.allowed_email_domains,
        };
        await createSSOProvider(request);
        toast.success("SSO provider created");
      } else {
        const request: SSOProviderUpdateRequest = {
          display_name: values.display_name.trim(),
          allowed_email_domains: values.allowed_email_domains,
          config: providerConfig,
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
      <Modal.Content width="sm" preventAccidentalClose>
        <Formik<SSOProviderFormValues>
          initialValues={initialValues}
          validationSchema={validationSchema}
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
            const isSaml = values.provider_type === "SAML";
            const providerTypeIcon =
              SSO_PROVIDER_DETAILS[values.provider_type as SSOProviderType]
                .icon;
            const domainChips: ChipItem[] = values.allowed_email_domains.map(
              (domain) => ({ id: domain, label: domain })
            );

            return (
              <Form>
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

                  <InputVertical title="Name" withLabel="name">
                    <InputTypeInField
                      name="name"
                      placeholder="company-a"
                      variant={isEditing ? "disabled" : undefined}
                    />
                  </InputVertical>

                  <InputVertical title="Display Name" withLabel="display_name">
                    <InputTypeInField
                      name="display_name"
                      placeholder="Company A"
                    />
                  </InputVertical>

                  {!isSaml && (
                    <>
                      <InputVertical title="Client ID" withLabel="client_id">
                        <InputTypeInField
                          name="client_id"
                          placeholder="Client ID"
                        />
                      </InputVertical>

                      <InputVertical
                        title="Client Secret"
                        withLabel="client_secret"
                      >
                        <PasswordInputTypeInField
                          name="client_secret"
                          placeholder="Client secret"
                          isNonRevealable={isEditing}
                        />
                      </InputVertical>

                      {values.provider_type === "OIDC" && (
                        <InputVertical
                          title="OpenID Configuration URL"
                          withLabel="openid_config_url"
                        >
                          <InputTypeInField
                            name="openid_config_url"
                            placeholder="https://example.com/.well-known/openid-configuration"
                          />
                        </InputVertical>
                      )}
                    </>
                  )}

                  {isSaml && (
                    <>
                      <InputVertical
                        title="IdP Entity ID"
                        withLabel="idp_entity_id"
                      >
                        <InputTypeInField
                          name="idp_entity_id"
                          placeholder="https://idp.example.com/entity"
                        />
                      </InputVertical>

                      <InputVertical
                        title="IdP SSO URL"
                        withLabel="idp_sso_url"
                      >
                        <InputTypeInField
                          name="idp_sso_url"
                          placeholder="https://idp.example.com/sso"
                        />
                      </InputVertical>

                      <InputVertical
                        title="IdP X.509 Certificate"
                        withLabel="idp_x509_cert"
                      >
                        <InputTextAreaField
                          name="idp_x509_cert"
                          placeholder="-----BEGIN CERTIFICATE-----"
                        />
                      </InputVertical>

                      <InputVertical
                        title="SP Entity ID"
                        withLabel="sp_entity_id"
                      >
                        <InputTypeInField
                          name="sp_entity_id"
                          placeholder="onyx"
                        />
                      </InputVertical>

                      <InputVertical
                        title="SP X.509 Certificate (Optional)"
                        withLabel="sp_x509_cert"
                      >
                        <InputTextAreaField
                          name="sp_x509_cert"
                          placeholder="-----BEGIN CERTIFICATE-----"
                        />
                      </InputVertical>

                      <InputVertical
                        title="SP Private Key (Optional)"
                        withLabel="sp_private_key"
                      >
                        <PasswordInputTypeInField
                          name="sp_private_key"
                          placeholder="-----BEGIN PRIVATE KEY-----"
                          isNonRevealable={isEditing}
                        />
                      </InputVertical>

                      <InputVertical
                        title="Email Attribute (Optional)"
                        withLabel="email_attribute"
                      >
                        <InputTypeInField
                          name="email_attribute"
                          placeholder="email"
                        />
                      </InputVertical>
                    </>
                  )}

                  <InputVertical
                    title="Allowed Email Domains (Optional)"
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

                  {provider?.redirect_uri && (
                    <InputVertical title={redirectLabel} withLabel>
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
