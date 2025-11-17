import { MCP_INTERNAL_URL } from "@/lib/constants";
import { NextRequest, NextResponse } from "next/server";

type RouteContext = {
  params?: Promise<{
    path?: string[];
  }>;
};

const proxyHandler = async (
  request: NextRequest,
  context: RouteContext
): Promise<Response> => {
  if (!isProxyEnabled()) {
    return NextResponse.json(
      {
        message:
          "This MCP proxy is only available in development mode. In production, something else (e.g. nginx) should handle this.",
      },
      { status: 404 }
    );
  }

  try {
    const resolvedParams = context.params ? await context.params : undefined;
    const targetUrl = buildTargetUrl(
      resolvedParams?.path,
      request.nextUrl.searchParams
    );
    const headers = buildForwardHeaders(request.headers);
    const fetchOptions: RequestInit & { duplex?: "half" } = {
      method: request.method,
      headers,
      signal: request.signal,
    };

    if (supportsRequestBody(request) && request.body) {
      fetchOptions.body = request.body;
      fetchOptions.duplex = "half";
    }

    const response = await fetch(targetUrl, fetchOptions);
    return response;
  } catch (error: unknown) {
    console.error("MCP Proxy error:", error);
    return NextResponse.json(
      {
        message: "MCP Proxy error",
        error:
          error instanceof Error ? error.message : "An unknown error occurred",
      },
      { status: 500 }
    );
  }
};

const isProxyEnabled = (): boolean => {
  if (process.env.OVERRIDE_API_PRODUCTION === "true") {
    return true;
  }
  return process.env.NODE_ENV === "development";
};

const buildForwardHeaders = (requestHeaders: Headers): Headers => {
  const headers = new Headers(requestHeaders);
  headers.delete("host");
  headers.delete("connection");
  headers.delete("content-length");
  return headers;
};

const supportsRequestBody = (request: NextRequest): boolean => {
  const method = request.method.toUpperCase();
  return method !== "GET" && method !== "HEAD";
};

const trimSlashes = (value: string): string => value.replace(/^\/+|\/+$/g, "");

const buildTargetUrl = (
  pathSegments: string[] | undefined,
  searchParams: URLSearchParams
): string => {
  const target = new URL(MCP_INTERNAL_URL);
  const forwardedPath = pathSegments?.filter(Boolean).join("/") ?? "";

  const basePath = trimSlashes(target.pathname);
  const combinedPath = [basePath, trimSlashes(forwardedPath)]
    .filter(Boolean)
    .join("/");

  target.pathname = combinedPath ? `/${combinedPath}` : "/";
  const queryString = searchParams.toString();
  target.search = queryString;

  return target.toString();
};

type Handler = (
  request: NextRequest,
  context: RouteContext
) => Promise<Response>;

const handler: Handler = proxyHandler;

export const GET = handler;
export const POST = handler;
export const PUT = handler;
export const PATCH = handler;
export const DELETE = handler;
export const HEAD = handler;
export const OPTIONS = handler;
