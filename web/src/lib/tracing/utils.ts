import { SvgBraintrust, SvgLangfuse } from "@opal/logos";
import type { IconFunctionComponent } from "@opal/types";
import type { TracingProviderType } from "@/lib/tracing/types";

export interface TracingFieldSpec {
  // Form field name. The secret field is always sent as the provider `api_key`;
  // config field names map to keys in the provider `config` object.
  name: string;
  label: string;
  placeholder?: string;
  help?: string;
  optional?: boolean;
  defaultValue?: string;
}

export interface TracingProviderDetail {
  label: string;
  description: string;
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
    description: "LLM evaluation and monitoring",
    logo: SvgBraintrust,
    secretField: {
      name: "api_key",
      label: "API Key",
      placeholder: "API Key",
      help: "Paste your [API key](https://www.braintrust.dev/app) from Braintrust.",
    },
    configFields: [
      {
        name: "project",
        label: "Project Name",
        placeholder: "Onyx",
        optional: true,
        defaultValue: "Onyx",
        help: "Braintrust project name traces are logged to.",
      },
      {
        name: "api_url",
        label: "API URL",
        placeholder: "https://api.braintrust.dev",
        optional: true,
        help: "Default to the US region. Paste your Braintrust API URL for other regions or self-hosting.",
      },
    ],
  },
  langfuse: {
    label: "Langfuse",
    description: "Cloud or self-hosted open-source observability platform",
    logo: SvgLangfuse,
    secretField: {
      name: "api_key",
      label: "Secret Key",
      placeholder: "Secret Key",
      help: "Paste your [API key](https://cloud.langfuse.com) from Langfuse.",
    },
    configFields: [
      {
        name: "public_key",
        label: "Public Key",
        placeholder: "Public Key",
      },
      {
        name: "host",
        label: "API Base URL",
        placeholder: "https://cloud.langfuse.com",
        optional: true,
        help: "Default to EU region. Paste your Langfuse base URL for other regions or self-hosting.",
      },
    ],
  },
};

export const TRACING_PROVIDER_ORDER = Object.keys(
  TRACING_PROVIDER_DETAILS
) as TracingProviderType[];
