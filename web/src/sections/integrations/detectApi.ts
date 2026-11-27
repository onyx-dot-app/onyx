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
  | {
      shape: "rest";
      baseUrl: string;
      /** Why Onyx could not check the URL, with the server's detail. Null
       * when the URL answered and is not a spec or a GraphQL endpoint. */
      warning: { reason: "unreachable" | "tooLarge"; detail: string } | null;
    }
  | {
      shape: "graphql";
      config: GraphQLConfig;
      queries: number;
      mutations: number;
    };

/** The largest spec or schema file, as the backend limits it. */
export const SPEC_MAX_SIZE_KB = 5 * 1024;

/** True when pasted or typed spec text is over `SPEC_MAX_SIZE_KB` in UTF-8. */
export function specTextTooLarge(text: string): boolean {
  return new Blob([text]).size > SPEC_MAX_SIZE_KB * 1024;
}

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
 * base URL with no spec. A URL that Onyx cannot reach, or whose answer is
 * over the spec size limit, is a REST base URL with the reason. Null when the API needs a URL that is missing. Throws when
 * the file is not a spec that Onyx can add, the URL is a spec that Onyx
 * cannot add, or a check fails with no answer.
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
    if (isUnreachable(error)) {
      return restResult(url, { reason: "unreachable", detail: error.message });
    }
    // Onyx stops reading at the size limit, before it knows if the answer is
    // a spec, so a REST base URL with a large answer stays possible.
    if (error instanceof FetchError && error.status === 413) {
      return restResult(url, { reason: "tooLarge", detail: error.message });
    }
    // A spec that Onyx cannot add, or a failed check, stops here. Else it is
    // not a spec; try GraphQL next.
    if (!isNotThisKind(error) || isSpecError(error)) throw error;
  }
  try {
    return graphqlResult(await introspectGraphQL(url));
  } catch (error) {
    if (isUnreachable(error)) {
      return restResult(url, { reason: "unreachable", detail: error.message });
    }
    if (!isNotThisKind(error)) throw error;
    return restResult(url, null);
  }
}

function restResult(
  url: string,
  warning: Extract<DetectedApi, { shape: "rest" }>["warning"]
): DetectedApi {
  return { shape: "rest", baseUrl: apiBaseUrl(url), warning };
}

/** The URL is blocked, timed out, failed to connect or gave a non-2xx
 * answer. */
function isUnreachable(error: unknown): error is FetchError {
  return error instanceof FetchError && error.status === 502;
}

function isSpecError(error: unknown): boolean {
  return (
    error instanceof FetchError && error.info?.error_code === "VALIDATION_ERROR"
  );
}

/** Onyx checked the URL and it is not this kind of API. Any other failure (no
 * permission, an Onyx error) is not an answer. */
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
  if (!specUrl) return null;
  try {
    return apiBaseUrl(new URL(baseUrl.trim() || "/", specUrl).href);
  } catch {
    // A variable with no default in the port, such as `:{port}`, is no URL;
    // the admin sets it in the Base URL field.
    return apiBaseUrl(baseUrl.trim());
  }
}

/** The tool appends paths that start with "/", so drop a trailing one. */
function apiBaseUrl(url: string): string {
  return url.replace(/\/+$/, "");
}

/** A REST base URL to save: a valid http(s) URL with no trailing slash, or
 * null when the value is not one. */
export function restBaseUrl(value: string): string | null {
  return normalizedUrl(value) ? apiBaseUrl(value.trim()) : null;
}

/** `fallback` (the URL entered with an upload) when given, else the spec's
 * server URL resolved against `url`, else the root of `url`. */
function openApiResult(
  view: OpenApiConfigView,
  url: string | null,
  fallback: string | null
): DetectedApi | null {
  const baseUrl = fallback ?? specBaseUrl(view.base_url, url);
  // Onyx fills server variables with their defaults; a "{" left in the URL is
  // a variable with no default. The admin sets it, or fixes a non-http(s) one.
  const baseUrlGuessed =
    fallback !== null ||
    !view.base_url.trim() ||
    view.base_url.includes("{") ||
    (baseUrl !== null && restBaseUrl(baseUrl) === null);
  return baseUrl
    ? {
        shape: "openapi",
        view: { ...view, base_url: baseUrl },
        baseUrlGuessed,
      }
    : null;
}

function graphqlResult(config: GraphQLConfig): DetectedApi {
  const sdl = withoutStringsAndComments(config.graphql_schema);
  return {
    shape: "graphql",
    config,
    queries: rootFieldCount(sdl, rootTypeName(sdl, "query", "Query")),
    mutations: rootFieldCount(sdl, rootTypeName(sdl, "mutation", "Mutation")),
  };
}

/** The SDL without strings and comments, which can hold braces and colons.
 * One linear pass, so a quote in a comment or a "#" in a string does not hide
 * what follows, and an unclosed quote does not rescan the rest. */
function withoutStringsAndComments(sdl: string): string {
  let kept = "";
  let i = 0;
  while (i < sdl.length) {
    if (sdl.startsWith('"""', i)) {
      const close = sdl.indexOf('"""', i + 3);
      i = close === -1 ? sdl.length : close + 3;
    } else if (sdl[i] === '"') {
      i++;
      while (i < sdl.length && sdl[i] !== '"' && sdl[i] !== "\n") {
        i += sdl[i] === "\\" ? 2 : 1;
      }
      if (sdl[i] === '"') i++;
    } else if (sdl[i] === "#") {
      const close = sdl.indexOf("\n", i);
      i = close === -1 ? sdl.length : close;
    } else {
      kept += sdl[i];
      i++;
    }
  }
  return kept;
}

/** The root type of an operation. The default name applies only when the SDL
 * has no `schema { ... }` block; with one, an undeclared operation has none. */
function rootTypeName(
  sdl: string,
  operation: "query" | "mutation",
  fallback: string
): string | null {
  // indexOf, not a regex with "[^{]*", so a header with no brace after it
  // does not rescan the rest of the SDL for each match.
  const start = /\bschema\s*[@{]/.exec(sdl)?.index;
  const open = start === undefined ? -1 : sdl.indexOf("{", start);
  const close = open === -1 ? -1 : sdl.indexOf("}", open);
  if (close === -1) return fallback;
  return (
    new RegExp(`\\b${operation}\\s*:\\s*([A-Za-z_]\\w*)`).exec(
      sdl.slice(open + 1, close)
    )?.[1] ?? null
  );
}

/** The number of fields of an object type in SDL, its extensions included;
 * 0 when it is missing. */
function rootFieldCount(sdl: string, typeName: string | null): number {
  if (typeName === null) return 0;
  const header = new RegExp(`\\btype\\s+${typeName}\\b`, "g");
  let count = 0;
  for (let match = header.exec(sdl); match; match = header.exec(sdl)) {
    const open = sdl.indexOf("{", header.lastIndex);
    if (open === -1) break;
    const block = blockFields(sdl, open + 1);
    count += block.count;
    // Go on after the block, so headers before one brace are scanned once.
    header.lastIndex = block.end;
  }
  return count;
}

/** The number of fields in the block whose body starts at `bodyStart`, and
 * the index after its closing brace. */
function blockFields(
  sdl: string,
  bodyStart: number
): { count: number; end: number } {
  let end = bodyStart;
  for (let depth = 1; end < sdl.length && depth > 0; end++) {
    if (sdl[end] === "{") depth++;
    else if (sdl[end] === "}") depth--;
  }
  // Arguments hold colons too; keep only the text outside parentheses, in one
  // pass so deep nesting stays linear.
  let body = "";
  let parens = 0;
  for (const char of sdl.slice(bodyStart, end - 1)) {
    if (char === "(") parens++;
    else if (char === ")") parens = Math.max(0, parens - 1);
    else if (parens === 0) body += char;
  }
  return { count: body.match(/[A-Za-z_]\w*\s*:/g)?.length ?? 0, end };
}
