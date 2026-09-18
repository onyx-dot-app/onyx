"use client";

import { useTranslations } from "next-intl";
import { useSWRConfig } from "swr";
import { FileUploadFormField } from "@/components/Field";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import { Section } from "@/layouts/general-layouts";
import { InputDivider, InputPadder, InputVertical, toast } from "@opal/layouts";
import {
  LLMProviderFormProps,
  LLMProviderName,
  LLMProviderView,
} from "@/lib/languageModels/types";
import * as Yup from "yup";
import {
  useInitialValues,
  buildValidationSchema,
  BaseLLMFormValues,
} from "@/sections/modals/languageModels/utils";
import { submitProvider } from "@/sections/modals/languageModels/svc";
import { LLMProviderConfiguredSource } from "@/lib/analytics/utils";
import {
  ModelSelectionField,
  DisplayNameField,
  ModelAccessField,
  ModalWrapper,
} from "@/sections/modals/languageModels/shared";
import { refreshLlmProviderCaches } from "@/lib/languageModels/cache";

const OCI_DEFAULT_REGION = "us-chicago-1";

// Keys use LiteLLM's OCI_* env-var spellings; the backend maps them to the
// matching `oci_*` completion kwargs (see custom_config_mapping.py).
const FIELD_OCI_REGION = "custom_config.OCI_REGION";
const FIELD_OCI_COMPARTMENT_ID = "custom_config.OCI_COMPARTMENT_ID";
const FIELD_OCI_TENANCY = "custom_config.OCI_TENANCY";
const FIELD_OCI_USER = "custom_config.OCI_USER";
const FIELD_OCI_FINGERPRINT = "custom_config.OCI_FINGERPRINT";
const FIELD_OCI_KEY = "custom_config.OCI_KEY";

interface OCIModalValues extends BaseLLMFormValues {
  custom_config: {
    OCI_REGION: string;
    OCI_COMPARTMENT_ID: string;
    OCI_TENANCY: string;
    OCI_USER: string;
    OCI_FINGERPRINT: string;
    OCI_KEY: string;
  };
}

interface OCIModalInternalsProps {
  existingLlmProvider: LLMProviderView | undefined;
  isOnboarding: boolean;
}

function OCIModalInternals({
  existingLlmProvider,
  isOnboarding,
}: OCIModalInternalsProps) {
  const t = useTranslations("admin.languageModels.modals");

  return (
    <>
      <InputPadder>
        <Section gap={4}>
          <InputVertical
            withLabel={FIELD_OCI_REGION}
            title={t("oci.regionField.title")}
            subDescription={t("oci.regionField.description")}
          >
            <InputTypeInField
              name={FIELD_OCI_REGION}
              placeholder={OCI_DEFAULT_REGION}
            />
          </InputVertical>

          <InputVertical
            withLabel={FIELD_OCI_COMPARTMENT_ID}
            title={t("oci.compartmentIdField.title")}
            subDescription={t("oci.compartmentIdField.description")}
          >
            <InputTypeInField
              name={FIELD_OCI_COMPARTMENT_ID}
              // oxlint-disable-next-line i18n/no-raw-jsx-text -- OCID prefix, not copy
              placeholder="ocid1.compartment.oc1.."
            />
          </InputVertical>

          <InputVertical
            withLabel={FIELD_OCI_TENANCY}
            title={t("oci.tenancyField.title")}
            subDescription={t("oci.tenancyField.description")}
          >
            <InputTypeInField
              name={FIELD_OCI_TENANCY}
              // oxlint-disable-next-line i18n/no-raw-jsx-text -- OCID prefix, not copy
              placeholder="ocid1.tenancy.oc1.."
            />
          </InputVertical>

          <InputVertical
            withLabel={FIELD_OCI_USER}
            title={t("oci.userField.title")}
            subDescription={t("oci.userField.description")}
          >
            <InputTypeInField
              name={FIELD_OCI_USER}
              // oxlint-disable-next-line i18n/no-raw-jsx-text -- OCID prefix, not copy
              placeholder="ocid1.user.oc1.."
            />
          </InputVertical>

          <InputVertical
            withLabel={FIELD_OCI_FINGERPRINT}
            title={t("oci.fingerprintField.title")}
            subDescription={t("oci.fingerprintField.description")}
          >
            <InputTypeInField
              name={FIELD_OCI_FINGERPRINT}
              // oxlint-disable-next-line i18n/no-raw-jsx-text -- fingerprint format, not copy
              placeholder="12:34:56:78:90:ab:cd:ef:12:34:56:78:90:ab:cd:ef"
            />
          </InputVertical>
        </Section>
      </InputPadder>

      <InputPadder>
        <InputVertical
          withLabel={FIELD_OCI_KEY}
          title={t("oci.privateKeyField.title")}
          subDescription={t("oci.privateKeyField.description")}
        >
          <FileUploadFormField name={FIELD_OCI_KEY} label="" />
        </InputVertical>
      </InputPadder>

      {!isOnboarding && (
        <>
          <InputDivider />
          <DisplayNameField />
        </>
      )}

      <InputDivider />
      <ModelSelectionField shouldShowAutoUpdateToggle={false} />

      {!isOnboarding && (
        <>
          <InputDivider />
          <ModelAccessField />
        </>
      )}
    </>
  );
}

export default function OCIModal({
  variant = "llm-configuration",
  existingLlmProvider,
  shouldMarkAsDefault,
  onOpenChange,
  onSuccess,
  analyticsSource,
}: LLMProviderFormProps) {
  const t = useTranslations("admin.languageModels.modals");
  const isOnboarding = variant === "onboarding";
  const { mutate } = useSWRConfig();

  const onClose = () => onOpenChange?.(false);

  const initialValues: OCIModalValues = {
    ...useInitialValues(isOnboarding, LLMProviderName.OCI, existingLlmProvider),
    custom_config: {
      OCI_REGION:
        (existingLlmProvider?.custom_config?.OCI_REGION as string) ??
        OCI_DEFAULT_REGION,
      OCI_COMPARTMENT_ID:
        (existingLlmProvider?.custom_config?.OCI_COMPARTMENT_ID as string) ??
        "",
      OCI_TENANCY:
        (existingLlmProvider?.custom_config?.OCI_TENANCY as string) ?? "",
      OCI_USER: (existingLlmProvider?.custom_config?.OCI_USER as string) ?? "",
      OCI_FINGERPRINT:
        (existingLlmProvider?.custom_config?.OCI_FINGERPRINT as string) ?? "",
      OCI_KEY: (existingLlmProvider?.custom_config?.OCI_KEY as string) ?? "",
    },
  };

  const validationSchema = buildValidationSchema(t, isOnboarding, {
    extra: {
      custom_config: Yup.object({
        OCI_REGION: Yup.string().required(t("oci.validation.regionRequired")),
        OCI_COMPARTMENT_ID: Yup.string().required(
          t("oci.validation.compartmentIdRequired")
        ),
        OCI_TENANCY: Yup.string().required(
          t("oci.validation.tenancyRequired")
        ),
        OCI_USER: Yup.string().required(t("oci.validation.userRequired")),
        OCI_FINGERPRINT: Yup.string().required(
          t("oci.validation.fingerprintRequired")
        ),
        OCI_KEY: Yup.string().required(
          t("oci.validation.privateKeyRequired")
        ),
      }),
    },
  });

  return (
    <ModalWrapper
      providerName={LLMProviderName.OCI}
      llmProvider={existingLlmProvider}
      onClose={onClose}
      initialValues={initialValues}
      validationSchema={validationSchema}
      onSubmit={async (values, { setSubmitting, setStatus }) => {
        const filteredCustomConfig = Object.fromEntries(
          Object.entries(values.custom_config || {}).filter(([, v]) => v !== "")
        );

        const submitValues = {
          ...values,
          custom_config:
            Object.keys(filteredCustomConfig).length > 0
              ? filteredCustomConfig
              : undefined,
        };

        await submitProvider({
          t,
          analyticsSource:
            analyticsSource ??
            (isOnboarding
              ? LLMProviderConfiguredSource.CHAT_ONBOARDING
              : LLMProviderConfiguredSource.ADMIN_PAGE),
          providerName: LLMProviderName.OCI,
          values: submitValues,
          initialValues,
          existingLlmProvider,
          shouldMarkAsDefault,
          setStatus,
          setSubmitting,
          onClose,
          onSuccess: async () => {
            if (onSuccess) {
              await onSuccess();
            } else {
              await refreshLlmProviderCaches(mutate);
              toast.success(
                existingLlmProvider
                  ? t("toasts.providerUpdated")
                  : t("toasts.providerEnabled")
              );
            }
          },
        });
      }}
    >
      <OCIModalInternals
        existingLlmProvider={existingLlmProvider}
        isOnboarding={isOnboarding}
      />
    </ModalWrapper>
  );
}
