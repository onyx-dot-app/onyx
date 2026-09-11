import type {
  Api,
  Model,
  SimpleStreamOptions,
  StreamFunction,
} from "@earendil-works/pi-ai";
import { builtinModels } from "@earendil-works/pi-ai/providers/all";
import { streamSimple as completions } from "@earendil-works/pi-ai/api/openai-completions";
import { streamSimple as responses } from "@earendil-works/pi-ai/api/openai-responses";
import { streamSimple as anthropic } from "@earendil-works/pi-ai/api/anthropic-messages";
import { streamSimple as azure } from "@earendil-works/pi-ai/api/azure-openai-responses";
import { streamSimple as google } from "@earendil-works/pi-ai/api/google-generative-ai";
import { streamSimple as vertex } from "@earendil-works/pi-ai/api/google-vertex";
import { streamSimple as bedrock } from "@earendil-works/pi-ai/api/bedrock-converse-stream";
import { z } from "zod";
import {
  fauxProvider,
  fauxAssistantMessage,
} from "@earendil-works/pi-ai/providers/faux";
import type { Start } from "./protocol";
import { vertexAnthropic } from "./vertex-anthropic";

const catalog = builtinModels();
const dispatch: StreamFunction<Api, SimpleStreamOptions> = (
  model,
  context,
  options,
) => {
  switch (model.api) {
    case "openai-completions":
      return completions(
        model as Model<"openai-completions">,
        context,
        options,
      );
    case "openai-responses":
      return responses(model as Model<"openai-responses">, context, options);
    case "anthropic-messages":
      return anthropic(model as Model<"anthropic-messages">, context, options);
    case "azure-openai-responses":
      return azure(model as Model<"azure-openai-responses">, context, options);
    case "google-generative-ai":
      return google(model as Model<"google-generative-ai">, context, options);
    case "google-vertex":
      return vertex(model as Model<"google-vertex">, context, options);
    case "bedrock-converse-stream":
      return bedrock(
        model as Model<"bedrock-converse-stream">,
        context,
        options,
      );
    default: {
      const provider = catalog.getProvider(model.provider);
      if (!provider) throw new Error(`Unsupported Pi API: ${model.api}`);
      return provider.streamSimple(model, context, options);
    }
  }
};
const aliases: Record<string, string> = {
  azure: "azure-openai-responses",
  gemini: "google",
  vertex_ai: "google-vertex",
  bedrock: "amazon-bedrock",
  bedrock_converse: "amazon-bedrock",
};
const surfaces: Record<string, string> = {
  openai_chat_completions: "openai-completions",
  openai_responses: "openai-responses",
  anthropic_messages: "anthropic-messages",
};
const stringMap = z.record(z.string(), z.string());

export function resolveProvider(start: Start) {
  const config = start.config;
  if (start.mockResponse != null) {
    const mock = fauxProvider({
      provider: "onyx-test",
      models: [{ id: config.model_name }],
      tokensPerSecond: 10000,
    });
    mock.setResponses([fauxAssistantMessage(start.mockResponse)]);
    return {
      model: mock.getModel(),
      stream: mock.provider.streamSimple,
      options: {} as SimpleStreamOptions,
      body: {} as Record<string, unknown>,
    };
  }
  const provider = aliases[config.model_provider] ?? config.model_provider;
  const isVertexAnthropic =
    !start.apiSurface &&
    provider === "google-vertex" &&
    config.model_name.includes("claude");
  const known =
    catalog.getModel(provider, config.model_name) ??
    (isVertexAnthropic
      ? catalog.getModel("anthropic", config.model_name.replace("@", "-"))
      : undefined);
  const api =
    (start.apiSurface && surfaces[start.apiSurface]) ||
    (isVertexAnthropic ? "anthropic-messages" : known?.api) ||
    {
      anthropic: "anthropic-messages",
      openai: "openai-responses",
      google: "google-generative-ai",
      "google-vertex": "google-vertex",
      "amazon-bedrock": "bedrock-converse-stream",
      "azure-openai-responses": "azure-openai-responses",
    }[provider] ||
    "openai-completions";
  const baseUrl =
    (typeof start.options.api_base === "string"
      ? start.options.api_base
      : undefined) ||
    config.api_base ||
    known?.baseUrl ||
    catalog.getProvider(provider)?.baseUrl;
  if (!baseUrl && api === "openai-completions")
    throw new Error(`Provider ${provider} requires an API base`);
  const model: Model<Api> = {
    ...known,
    id: config.deployment_name || config.model_name,
    name: config.model_name,
    provider,
    api,
    baseUrl: baseUrl ?? "",
    reasoning:
      known?.reasoning ?? /gpt-5|o[134]|claude|gemini/.test(config.model_name),
    input: known?.input ?? ["text", "image"],
    contextWindow: config.max_input_tokens,
    maxTokens: Math.min(known?.maxTokens ?? 16384, 32768),
    cost: known?.cost ?? { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
  };
  if (
    ["ollama_chat", "ollama", "lm_studio"].includes(provider) &&
    !model.baseUrl.endsWith("/v1")
  )
    model.baseUrl = model.baseUrl.replace(/\/$/, "") + "/v1";
  const stream = isVertexAnthropic ? vertexAnthropic(start) : dispatch;
  const raw = start.options;
  const env = { ...config.custom_config };
  const envKeys: Record<string, string> = {
    aws_access_key_id: "AWS_ACCESS_KEY_ID",
    aws_secret_access_key: "AWS_SECRET_ACCESS_KEY",
    aws_session_token: "AWS_SESSION_TOKEN",
    aws_region_name: "AWS_REGION",
    vertex_project: "GOOGLE_CLOUD_PROJECT",
    vertex_location: "GOOGLE_CLOUD_LOCATION",
  };
  for (const [key, target] of Object.entries(envKeys))
    if (typeof raw[key] === "string") env[target] = raw[key];
  if (provider === "google-vertex") env.GOOGLE_CLOUD_LOCATION ??= "global";
  if (
    provider === "amazon-bedrock" &&
    (typeof raw.api_key === "string" || config.api_key)
  )
    env.AWS_BEARER_TOKEN_BEDROCK =
      typeof raw.api_key === "string" ? raw.api_key : config.api_key!;
  if (config.api_version) env.AZURE_OPENAI_API_VERSION = config.api_version;
  if (config.api_base && provider === "azure-openai-responses")
    env.AZURE_OPENAI_BASE_URL = config.api_base;
  if (config.deployment_name && provider === "azure-openai-responses")
    env.AZURE_OPENAI_DEPLOYMENT_NAME = config.deployment_name;
  const options: SimpleStreamOptions = {
    apiKey:
      typeof raw.api_key === "string"
        ? raw.api_key
        : (config.api_key ??
          (typeof raw.azure_ad_token === "string"
            ? raw.azure_ad_token
            : undefined)),
    temperature: model.reasoning ? undefined : config.temperature,
    env,
    transport: "sse",
    maxRetries: 2,
    headers: {
      ...(raw.extra_headers ? stringMap.parse(raw.extra_headers) : {}),
      ...(typeof raw.azure_ad_token === "string"
        ? { Authorization: `Bearer ${raw.azure_ad_token}`, "api-key": null }
        : {}),
    },
    timeoutMs: 120000,
    sessionId: start.sessionId ?? undefined,
  };
  // Mandatory policy overrides are applied after provider payload construction.
  const body = {
    ...z.record(z.string(), z.unknown()).parse(raw.extra_body ?? {}),
  };
  if (
    api === "openai-completions" ||
    api === "openai-responses" ||
    api === "azure-openai-responses"
  ) {
    for (const key of ["store", "metadata", "user", "service_tier"])
      if (key in raw) body[key] = raw[key];
  } else if (api === "anthropic-messages" && typeof raw.user === "string") {
    options.metadata = { user_id: raw.user };
  }
  return { model, stream, options, body };
}
