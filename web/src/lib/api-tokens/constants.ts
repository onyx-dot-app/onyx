import type { ApiTokenPlatform, ApiTokenValue } from "@/lib/api-tokens/types";

export const API_TOKENS_URL = "/api/admin/api-tokens";

/** An empty key field. */
export const EMPTY_API_TOKEN_VALUE: ApiTokenValue = { type: "new", value: "" };

/** Brand names for the "Reuse … API Keys" heading. Unlisted platforms show their id. */
export const API_TOKEN_PLATFORM_LABELS = new Map<ApiTokenPlatform, string>([
  ["anthropic", "Anthropic"],
  ["azure", "Azure"],
  ["bedrock", "Bedrock"],
  ["bifrost", "Bifrost"],
  ["braintrust", "Braintrust"],
  ["brave", "Brave"],
  ["cohere", "Cohere"],
  ["elevenlabs", "ElevenLabs"],
  ["exa", "Exa"],
  ["firecrawl", "Firecrawl"],
  ["google", "Google"],
  ["google_pse", "Google PSE"],
  ["hook", "Hook"],
  ["langfuse", "Langfuse"],
  ["litellm", "LiteLLM"],
  ["litellm_proxy", "LiteLLM"],
  ["lm_studio", "LM Studio"],
  ["nebius_tokenfactory", "Nebius"],
  ["ollama_chat", "Ollama"],
  ["openai", "OpenAI"],
  ["openai_compatible", "OpenAI-compatible"],
  ["openrouter", "OpenRouter"],
  ["portkey", "Portkey"],
  ["searxng", "SearXNG"],
  ["serper", "Serper"],
  ["tavily", "Tavily"],
  ["unstructured", "Unstructured"],
  ["vercel_ai_gateway", "Vercel AI Gateway"],
  ["vertex_ai", "Vertex AI"],
  ["voyage", "Voyage"],
  ["zoom", "Zoom"],
]);
