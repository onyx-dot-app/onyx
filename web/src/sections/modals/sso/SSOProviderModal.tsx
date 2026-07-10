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
  client_id: string;
  client_secret: string;
  openid_config_url: string;
  allowed_email_domains: string[];
}

export function SSOProviderModal({ provider, onSaved }: SSOProviderModalProps) {
  const onClose = useModalClose();
  const isEditing = provider !== null;
  const initialSecret = provider?.config.client_secret ?? "";
  const [domainInput, setDomainInput] = useState("");

  const initialValues: SSOProviderFormValues = {
    provider_type: provider?.provider_type ?? "GOOGLE_OAUTH",
    name: provider?.name ?? "",
    display_name: provider?.display_name ?? "",
    client_id: provider?.config.client_id ?? "",
    client_secret: initialSecret,
    openid_config_url: provider?.config.openid_config_url ?? "",
    allowed_email_domains: provider?.allowed_email_domains ?? [],
  };

  const validationSchema = Yup.object({
    provider_type: Yup.string()
      .oneOf(["GOOGLE_OAUTH", "OIDC"])
      .required("Provider type is required"),
    name: Yup.string()
      .required("Name is required")
      .matches(
        /^[a-z0-9-]+$/,
        "Use lowercase letters, numbers, and hyphens only"
      ),
    display_name: Yup.string().required("Display name is required"),
    client_id: Yup.string().required("Client ID is required"),
    client_secret: isEditing
      ? Yup.string()
      : Yup.string().required("Client secret is required"),
    openid_config_url: Yup.string().when("provider_type", {
      is: "OIDC",
      then: (schema) => schema.required("OpenID configuration URL is required"),
      otherwise: (schema) => schema.optional(),
    }),
    allowed_email_domains: Yup.array().of(Yup.string()).optional(),
  });

  async function handleSubmit(
    values: SSOProviderFormValues,
    { setSubmitting }: { setSubmitting: (isSubmitting: boolean) => void }
  ) {
    // Unchanged secret sends the masked placeholder back and the backend
    // restores the stored value from it. On create initialSecret is "" and Yup
    // requires a real secret, so secretChanged is always true there.
    const secretChanged = values.client_secret !== initialSecret;
    const config: Record<string, string> = {
      client_id: values.client_id.trim(),
      client_secret: secretChanged ? values.client_secret : initialSecret,
    };

    if (values.provider_type === "OIDC") {
      config.openid_config_url = values.openid_config_url.trim();
    }

    try {
      if (!isEditing) {
        const request: SSOProviderCreateRequest = {
          name: values.name.trim(),
          display_name: values.display_name.trim(),
          provider_type: values.provider_type as SSOProviderType,
          config,
          allowed_email_domains: values.allowed_email_domains,
        };

        await createSSOProvider(request);
        toast.success("SSO provider created");
      } else {
        const request: SSOProviderUpdateRequest = {
          display_name: values.display_name.trim(),
          allowed_email_domains: values.allowed_email_domains,
          config,
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
                      : "Add a Google or OIDC provider for sign-in."
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
                      placeholder="google-workspace"
                      variant={isEditing ? "disabled" : undefined}
                    />
                  </InputVertical>

                  <InputVertical title="Display Name" withLabel="display_name">
                    <InputTypeInField
                      name="display_name"
                      placeholder="Google Workspace"
                    />
                  </InputVertical>

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
                    <InputVertical title="Redirect URI" withLabel>
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
                          tooltip="Copy redirect URI"
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
