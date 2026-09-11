import type Anthropic from "@anthropic-ai/sdk";
import { AnthropicVertex } from "@anthropic-ai/vertex-sdk";
import { GoogleAuth, OAuth2Client } from "google-auth-library";
import type {
  Api,
  Model,
  SimpleStreamOptions,
  StreamFunction,
} from "@earendil-works/pi-ai";
import {
  stream,
  type AnthropicEffort,
} from "@earendil-works/pi-ai/api/anthropic-messages";
import {
  adjustMaxTokensForThinking,
  buildBaseOptions,
  clampMaxTokensToContext,
} from "@earendil-works/pi-ai/api/simple-options";
import { z } from "zod";
import type { Start } from "./protocol";

/** Use Vertex authentication with Pi's native Anthropic messages and event parser. */
export function vertexAnthropic(
  start: Start,
): StreamFunction<Api, SimpleStreamOptions> {
  const raw = start.options;
  const credentials =
    typeof raw.vertex_credentials === "string"
      ? z
          .record(z.string(), z.unknown())
          .parse(JSON.parse(raw.vertex_credentials))
      : undefined;
  const googleAuth = new GoogleAuth({
    credentials,
    scopes: ["https://www.googleapis.com/auth/cloud-platform"],
  });
  const project = raw.vertex_project ?? credentials?.project_id;
  const accessToken =
    typeof raw.vertex_access_token === "string"
      ? raw.vertex_access_token
      : undefined;
  const tokenClient = accessToken ? new OAuth2Client() : undefined;
  tokenClient?.setCredentials({ access_token: accessToken });
  let client: AnthropicVertex | undefined;
  return (inputModel, context, options) => {
    client ??= new AnthropicVertex({
      ...(tokenClient ? { authClient: tokenClient } : { googleAuth }),
      defaultHeaders: z
        .record(z.string(), z.string())
        .parse(raw.extra_headers ?? {}),
      projectId: typeof project === "string" ? project : undefined,
      region:
        typeof raw.vertex_location === "string"
          ? raw.vertex_location
          : "global",
      baseURL: start.config.api_base ?? undefined,
      maxRetries: 2,
      timeout: 120000,
    });
    const model = inputModel as Model<"anthropic-messages">;
    const base = {
      ...buildBaseOptions(model, context, options),
      toolChoice: options?.toolChoice,
      // Pi uses the shared messages API. Vertex omits the unused batches API.
      client: client as unknown as Anthropic,
    };
    if (!options?.reasoning)
      return stream(model, context, { ...base, thinkingEnabled: false });
    if (model.compat?.forceAdaptiveThinking) {
      const mapped =
        model.thinkingLevelMap?.[options.reasoning] ?? options.reasoning;
      const effort = z
        .enum(["low", "medium", "high", "xhigh", "max"])
        .parse(mapped === "minimal" ? "low" : mapped) satisfies AnthropicEffort;
      return stream(model, context, { ...base, thinkingEnabled: true, effort });
    }
    const adjusted = adjustMaxTokensForThinking(
      base.maxTokens,
      model.maxTokens,
      options.reasoning,
      options.thinkingBudgets,
    );
    const maxTokens = clampMaxTokensToContext(
      model,
      context,
      adjusted.maxTokens,
    );
    return stream(model, context, {
      ...base,
      maxTokens,
      thinkingEnabled: true,
      thinkingBudgetTokens: Math.min(
        adjusted.thinkingBudget,
        Math.max(0, maxTokens - 1024),
      ),
    });
  };
}
