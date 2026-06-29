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

export interface TracingProviderMeta {
  type: TracingProviderType;
  label: string;
  description: string;
  secretField: TracingFieldSpec;
  configFields: TracingFieldSpec[];
}

export const TRACING_PROVIDERS: TracingProviderMeta[] = [
  {
    type: "braintrust",
    label: "Braintrust",
    description: "LLM evaluation and monitoring",
    secretField: {
      name: "api_key",
      label: "API Key",
      placeholder: "API Key",
      help: "Paste your API key from Braintrust.",
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
    ],
  },
  {
    type: "langfuse",
    label: "Langfuse",
    description: "Cloud or self-hosted open-source observability platform",
    secretField: {
      name: "api_key",
      label: "Secret Key",
      placeholder: "Secret Key",
      help: "Paste your secret key from Langfuse.",
    },
    configFields: [
      {
        name: "public_key",
        label: "Public Key",
        placeholder: "Public Key",
        help: "Paste your public key from Langfuse.",
      },
      {
        name: "host",
        label: "API Base URL",
        placeholder: "https://cloud.langfuse.com",
        optional: true,
        help: "Defaults to the EU region. Paste your Langfuse base URL for other regions or self-hosting.",
      },
    ],
  },
];
