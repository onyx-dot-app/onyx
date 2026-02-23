import type { IconFunctionComponent } from "@opal/types";
import {
  SvgCpu,
  SvgOpenai,
  SvgClaude,
  SvgOllama,
  SvgCloud,
  SvgAws,
  SvgOpenrouter,
  SvgServer,
} from "@opal/icons";

const PROVIDER_ICONS: Record<string, IconFunctionComponent> = {
  openai: SvgOpenai,
  anthropic: SvgClaude,
  vertex_ai: SvgCloud,
  bedrock: SvgAws,
  azure: SvgCloud,

  ollama_chat: SvgOllama,
  openrouter: SvgOpenrouter,
  custom: SvgServer,
};

const PROVIDER_PRODUCT_NAMES: Record<string, string> = {
  openai: "GPT",
  anthropic: "Claude",
  vertex_ai: "Gemini",
  bedrock: "Amazon Bedrock",
  azure: "Azure OpenAI",
  litellm: "LiteLLM",
  ollama_chat: "Ollama",
  openrouter: "OpenRouter",

  custom: "Custom Models",
};

const PROVIDER_DISPLAY_NAMES: Record<string, string> = {
  openai: "OpenAI",
  anthropic: "Anthropic",
  vertex_ai: "Google Cloud Vertex AI",
  bedrock: "AWS",
  azure: "Microsoft Azure",
  litellm: "LiteLLM",
  ollama_chat: "Ollama",
  openrouter: "OpenRouter",

  custom: "Other providers or self-hosted",
};

export function getProviderTitle(providerName: string): string {
  return PROVIDER_PRODUCT_NAMES[providerName] ?? providerName;
}

export function getProviderDescription(providerName: string): string {
  return PROVIDER_DISPLAY_NAMES[providerName] ?? providerName;
}

export function getProviderIcon(providerName: string): IconFunctionComponent {
  return PROVIDER_ICONS[providerName] ?? SvgCpu;
}
