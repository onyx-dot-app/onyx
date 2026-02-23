import type { IconFunctionComponent } from "@opal/types";
import {
  SvgCpu,
  SvgOpenai,
  SvgClaude,
  SvgOllama,
  SvgCloud,
  SvgAws,
  SvgOpenrouter,
} from "@opal/icons";

const PROVIDER_DISPLAY_NAMES: Record<string, string> = {
  openai: "OpenAI",
  anthropic: "Anthropic",
  ollama_chat: "Ollama",
  azure: "Microsoft Azure Cloud",
  bedrock: "AWS Bedrock",
  vertex_ai: "Google Cloud Vertex AI",
  openrouter: "OpenRouter",
  custom: "Custom LLM",
};

const PROVIDER_ICONS: Record<string, IconFunctionComponent> = {
  openai: SvgOpenai,
  anthropic: SvgClaude,
  ollama_chat: SvgOllama,
  azure: SvgCloud,
  bedrock: SvgAws,
  vertex_ai: SvgCloud,
  openrouter: SvgOpenrouter,
  custom: SvgCpu,
};

export function getProviderDisplayName(providerName: string): string {
  return PROVIDER_DISPLAY_NAMES[providerName] ?? providerName;
}

export function getProviderIcon(providerName: string): IconFunctionComponent {
  return PROVIDER_ICONS[providerName] ?? SvgCpu;
}
