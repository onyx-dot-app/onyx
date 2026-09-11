import { GoogleGenAI, ResourceScope } from "@google/genai";
import type {
  Api,
  Model,
  SimpleStreamOptions,
  StreamFunction,
} from "@earendil-works/pi-ai";
import { streamSimple } from "@earendil-works/pi-ai/api/google-vertex";
import type { Start } from "./protocol";
import { googleAuthentication, vertexBaseUrl } from "./google-auth";

/** Inject a run-local client while retaining Pi's Google message and stream handling. */
export function vertexGoogle(
  start: Start,
): StreamFunction<Api, SimpleStreamOptions> {
  const apiKey =
    typeof start.options.api_key === "string"
      ? start.options.api_key
      : start.config.api_key;
  const auth = apiKey ? undefined : googleAuthentication(start);
  return (inputModel, context, options) => {
    const model = inputModel as Model<"google-vertex">;
    const baseUrl =
      (typeof start.options.api_base === "string"
        ? start.options.api_base
        : undefined) ||
      start.config.api_base ||
      vertexBaseUrl(auth?.location ?? "global");
    const headers: Record<string, string> = {};
    for (const [name, value] of Object.entries({
      ...model.headers,
      ...options?.headers,
    })) {
      if (typeof value === "string") headers[name] = value;
    }
    const client = new GoogleGenAI({
      vertexai: true,
      ...(auth
        ? {
            project: auth.project,
            location: auth.location,
            googleAuthOptions: {
              authClient: auth.authClient,
              scopes: auth.scopes,
            },
          }
        : { apiKey: apiKey! }),
      apiVersion: "v1",
      httpOptions: {
        baseUrl,
        ...(/\/projects\/[^/]+\/locations\/[^/]+(?:\/|$)/.test(baseUrl)
          ? { baseUrlResourceScope: ResourceScope.COLLECTION }
          : {}),
        ...(/\/v\d+(?:(?:alpha|beta)\d*)?(?:\/|$)/.test(baseUrl)
          ? { apiVersion: "" }
          : {}),
        headers,
      },
    });
    return streamSimple(model, context, { ...options, client });
  };
}
