import { FetchError } from "@/lib/fetcher";
import { importOpenApiSpec, introspectGraphQL } from "@/lib/integrations/svc";
import type {
  GraphQLConfig,
  OpenApiConfigView,
} from "@/lib/integrations/types";
import { normalizedUrl } from "@/sections/integrations/signIn";

/** What the Add flow found at a URL or in an uploaded spec. */
export type DetectedApi =
  | {
      shape: "openapi";
      view: OpenApiConfigView;
      /** The spec names no single server URL, so Onyx guessed the base URL
       * for the admin to check. */
      baseUrlGuessed: boolean;
    }
  | { shape: "rest"; baseUrl: string }
  | {
      shape: "graphql";
      config: GraphQLConfig;
      queries: number;
      mutations: number;
    };

export interface SpecFile {
  name: string;
  text: string;
}

export function isGraphQLFile(name: string): boolean {
  return /\.(graphql|graphqls|gql)$/i.test(name);
}

/**
 * Finds the kind of API. An uploaded `.graphql` file is a GraphQL schema for
 * the URL; another file is an OpenAPI spec. With only a URL: an OpenAPI spec
 * at the URL, else a GraphQL endpoint that answers introspection, else a REST
 * base URL with no spec. Null when the API needs a URL that is missing.
 * Throws when the file is not a spec that Onyx can add, the URL is a spec
 * that Onyx cannot add, or a check fails with no answer.
 */
export async function detectApi(
  url: string | null,
  file: SpecFile | null
): Promise<DetectedApi | null> {
  if (file && isGraphQLFile(file.name)) {
    return url
      ? graphqlResult({
          shape: "graphql",
          endpoint_url: url,
          graphql_schema: file.text,
        })
      : null;
  }
  if (file) {
    // The URL is the API's base URL here, not where the spec came from.
    const view = await importOpenApiSpec({ openapi_document: file.text });
    return openApiResult(view, url, url ? apiBaseUrl(url) : null);
  }
  if (!url) return null;
  try {
    const result = openApiResult(
      await importOpenApiSpec({ spec_url: url }),
      url,
      null
    );
    if (result) return result;
  } catch (error) {
    // A spec that Onyx cannot add, or a failed check, stops here. Else it is
    // not a spec; try GraphQL next.
    if (!isNotThisKind(error) || isSpecError(error)) throw error;
  }
  try {
    return graphqlResult(await introspectGraphQL(url));
  } catch (error) {
    if (!isNotThisKind(error)) throw error;
    return { shape: "rest", baseUrl: apiBaseUrl(url) };
  }
}

function isSpecError(error: unknown): boolean {
  return (
    error instanceof FetchError && error.info?.error_code === "VALIDATION_ERROR"
  );
}

/** Onyx checked the URL and it is not this kind of API. Any other failure
 * (no permission, a server error, no connection) is not an answer. */
function isNotThisKind(error: unknown): boolean {
  return error instanceof FetchError && error.status === 400;
}

/** A spec's server URL, resolved against the URL the spec came from when it
 * is relative. Null when it stays relative. */
export function specBaseUrl(
  baseUrl: string,
  specUrl: string | null
): string | null {
  if (normalizedUrl(baseUrl) !== null) return baseUrl.trim();
  return specUrl
    ? apiBaseUrl(new URL(baseUrl.trim() || "/", specUrl).href)
    : null;
}

/** The tool appends paths that start with "/", so drop a trailing one. */
function apiBaseUrl(url: string): string {
  return url.replace(/\/+$/, "");
}

/** The spec's server URL resolved against `url`. A spec with no single
 * server URL takes `fallback`, else the root of `url`. With a `fallback`, a
 * relative server URL takes it too: an uploaded spec has no location. */
function openApiResult(
  view: OpenApiConfigView,
  url: string | null,
  fallback: string | null
): DetectedApi | null {
  const baseUrlGuessed =
    !view.base_url.trim() ||
    (fallback !== null && normalizedUrl(view.base_url) === null);
  const baseUrl =
    (baseUrlGuessed ? fallback : null) ?? specBaseUrl(view.base_url, url);
  return baseUrl
    ? {
        shape: "openapi",
        view: { ...view, base_url: baseUrl },
        baseUrlGuessed,
      }
    : null;
}

function graphqlResult(config: GraphQLConfig): DetectedApi {
  const sdl = config.graphql_schema;
  return {
    shape: "graphql",
    config,
    queries: rootFieldCount(sdl, rootTypeName(sdl, "query", "Query")),
    mutations: rootFieldCount(sdl, rootTypeName(sdl, "mutation", "Mutation")),
  };
}

function rootTypeName(
  sdl: string,
  operation: "query" | "mutation",
  fallback: string
): string {
  const schema = /\bschema\b[^{]*\{([^}]*)\}/.exec(sdl)?.[1];
  const match = schema
    ? new RegExp(`\\b${operation}\\s*:\\s*([A-Za-z_]\\w*)`).exec(schema)
    : null;
  return match?.[1] ?? fallback;
}

/** The number of fields of an object type in SDL; 0 when it is missing. */
function rootFieldCount(sdl: string, typeName: string): number {
  const start = new RegExp(`\\btype\\s+${typeName}\\b[^{]*\\{`).exec(sdl);
  if (!start) return 0;
  let end = start.index + start[0].length;
  for (let depth = 1; end < sdl.length && depth > 0; end++) {
    if (sdl[end] === "{") depth++;
    else if (sdl[end] === "}") depth--;
  }
  let body = sdl
    .slice(start.index + start[0].length, end - 1)
    .replace(/"""[\s\S]*?"""/g, "")
    .replace(/"(?:[^"\\\n]|\\.)*"/g, "")
    .replace(/#[^\n]*/g, "");
  // Arguments hold colons too; drop them, inner pairs first.
  for (let previous = ""; previous !== body;) {
    previous = body;
    body = body.replace(/\([^()]*\)/g, "");
  }
  return body.match(/[A-Za-z_]\w*\s*:/g)?.length ?? 0;
}
