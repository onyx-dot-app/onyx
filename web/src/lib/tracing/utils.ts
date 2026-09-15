import type { useTranslations } from "next-intl";
import { SvgBraintrust, SvgLangfuse } from "@opal/logos";
import type { IconFunctionComponent } from "@opal/types";
import type { TracingProviderType } from "@/lib/tracing/types";

export type TracingTranslate = ReturnType<
  typeof useTranslations<"admin.tracing">
>;
export type TracingMessageKey = Parameters<TracingTranslate>[0];

export interface TracingFieldSpec {
  // Form field name. The secret field is always sent as the provider `api_key`;
  // config field names map to keys in the provider `config` object.
  name: string;
  // The user-facing text lives in the "admin.tracing" catalog namespace.
  labelKey: TracingMessageKey;
  descriptionKey?: TracingMessageKey;
  placeholderKey?: TracingMessageKey;
  // URLs and default values are not translated.
  placeholder?: string;
  optional?: boolean;
  defaultValue?: string;
}

export interface TracingProviderDetail {
  label: string;
  descriptionKey: TracingMessageKey;
  logo: IconFunctionComponent;
  secretField: TracingFieldSpec;
  configFields: TracingFieldSpec[];
}

export const TRACING_PROVIDER_DETAILS: Record<
  TracingProviderType,
  TracingProviderDetail
> = {
  braintrust: {
    label: "Braintrust",
    descriptionKey: "providers.braintrust.description",
    logo: SvgBraintrust,
    secretField: {
      name: "api_key",
      labelKey: "providers.braintrust.fields.apiKey.label",
      descriptionKey: "providers.braintrust.fields.apiKey.description",
    },
    configFields: [
      {
        name: "project",
        labelKey: "providers.braintrust.fields.project.label",
        placeholder: "Onyx",
        optional: true,
        defaultValue: "Onyx",
        descriptionKey: "providers.braintrust.fields.project.description",
      },
      {
        name: "api_url",
        labelKey: "providers.braintrust.fields.apiUrl.label",
        placeholder: "https://api.braintrust.dev",
        optional: true,
        descriptionKey: "providers.braintrust.fields.apiUrl.description",
      },
    ],
  },
  langfuse: {
    label: "Langfuse",
    descriptionKey: "providers.langfuse.description",
    logo: SvgLangfuse,
    secretField: {
      name: "api_key",
      labelKey: "providers.langfuse.fields.secretKey.label",
      descriptionKey: "providers.langfuse.fields.secretKey.description",
    },
    configFields: [
      {
        name: "public_key",
        labelKey: "providers.langfuse.fields.publicKey.label",
        placeholderKey: "providers.langfuse.fields.publicKey.placeholder",
      },
      {
        name: "host",
        labelKey: "providers.langfuse.fields.host.label",
        placeholder: "https://cloud.langfuse.com",
        optional: true,
        descriptionKey: "providers.langfuse.fields.host.description",
      },
    ],
  },
};

export const TRACING_PROVIDER_ORDER = Object.keys(
  TRACING_PROVIDER_DETAILS
) as TracingProviderType[];
