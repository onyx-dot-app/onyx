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
      /** The base URL is not one server URL of the spec, so the admin
       * checks it. */
      baseUrlGuessed: boolean;
    }
  | { shape: "rest"; baseUrl: string }
  | {
      shape: "graphql";
      config: GraphQLConfig;
      queries: number;
      mutations: number;
    };

/** The largest spec or schema file, as the backend limits it. */
export const SPEC_MAX_SIZE_KB = 5 * 1024;

export interface SpecFile {
  name: string;
  text: string;
}

function isGraphQLFile(name: string): boolean {
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

/** Onyx checked the URL and it is not this kind of API, or the URL did not
 * answer. Any other failure (no permission, an Onyx error) is not an answer. */
export function isNotThisKind(error: unknown): error is FetchError {
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
export function apiBaseUrl(url: string): string {
  return url.replace(/\/+$/, "");
}

/** `fallback` (the URL entered with an upload) when given, else the spec's
 * server URL resolved against `url`, else the root of `url`. */
function openApiResult(
  view: OpenApiConfigView,
  url: string | null,
  fallback: string | null
): DetectedApi | null {
  // Onyx fills server variables with their defaults; a "{" left in the URL is
  // a variable with no default, so the admin sets it.
  const baseUrlGuessed =
    fallback !== null || !view.base_url.trim() || view.base_url.includes("{");
  const baseUrl = fallback ?? specBaseUrl(view.base_url, url);
  return baseUrl
    ? {
        shape: "openapi",
        view: { ...view, base_url: baseUrl },
        baseUrlGuessed,
      }
    : null;
}

function graphqlResult(config: GraphQLConfig): DetectedApi {
  // Strings and comments can hold braces and colons. One pass, so a quote in
  // a comment or a "#" in a string does not hide what follows.
  const sdl = config.graphql_schema.replace(
    /"""[\s\S]*?"""|"(?:[^"\\\n]|\\.)*"|#[^\n]*/g,
    ""
  );
  return {
    shape: "graphql",
    config,
    queries: rootFieldCount(sdl, rootTypeName(sdl, "query", "Query")),
    mutations: rootFieldCount(sdl, rootTypeName(sdl, "mutation", "Mutation")),
  };
}

/** The root type of an operation. The default name applies only when the SDL
 * has no `schema { ... }` block; with one, an undeclared operation has none. */
function rootTypeName(
  sdl: string,
  operation: "query" | "mutation",
  fallback: string
): string | null {
  const schema = /\bschema\s*(?:@[^{]*)?\{([^}]*)\}/.exec(sdl)?.[1];
  if (schema === undefined) return fallback;
  return (
    new RegExp(`\\b${operation}\\s*:\\s*([A-Za-z_]\\w*)`).exec(schema)?.[1] ??
    null
  );
}

/** The number of fields of an object type in SDL, its extensions included;
 * 0 when it is missing. */
function rootFieldCount(sdl: string, typeName: string | null): number {
  if (typeName === null) return 0;
  const blocks = new RegExp(`\\btype\\s+${typeName}\\b[^{]*\\{`, "g");
  let count = 0;
  for (const start of sdl.matchAll(blocks)) {
    count += blockFieldCount(sdl, start.index + start[0].length);
  }
  return count;
}

function blockFieldCount(sdl: string, bodyStart: number): number {
  let end = bodyStart;
  for (let depth = 1; end < sdl.length && depth > 0; end++) {
    if (sdl[end] === "{") depth++;
    else if (sdl[end] === "}") depth--;
  }
  let body = sdl.slice(bodyStart, end - 1);
  // Arguments hold colons too; drop them, inner pairs first.
  for (let previous = ""; previous !== body;) {
    previous = body;
    body = body.replace(/\([^()]*\)/g, "");
  }
  return body.match(/[A-Za-z_]\w*\s*:/g)?.length ?? 0;
}
