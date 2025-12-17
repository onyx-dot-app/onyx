import { INTERNAL_URL } from "@/lib/constants";
import { NextRequest, NextResponse } from "next/server";

/* NextJS is annoying and makes use use a separate function for
each request type >:( */

export async function GET(
  request: NextRequest,
  props: { params: Promise<{ path: string[] }> }
) {
  const params = await props.params;
  return handleRequest(request, params.path);
}

export async function POST(
  request: NextRequest,
  props: { params: Promise<{ path: string[] }> }
) {
  const params = await props.params;
  return handleRequest(request, params.path);
}

export async function PUT(
  request: NextRequest,
  props: { params: Promise<{ path: string[] }> }
) {
  const params = await props.params;
  return handleRequest(request, params.path);
}

export async function PATCH(
  request: NextRequest,
  props: { params: Promise<{ path: string[] }> }
) {
  const params = await props.params;
  return handleRequest(request, params.path);
}

export async function DELETE(
  request: NextRequest,
  props: { params: Promise<{ path: string[] }> }
) {
  const params = await props.params;
  return handleRequest(request, params.path);
}

export async function HEAD(
  request: NextRequest,
  props: { params: Promise<{ path: string[] }> }
) {
  const params = await props.params;
  return handleRequest(request, params.path);
}

export async function OPTIONS(
  request: NextRequest,
  props: { params: Promise<{ path: string[] }> }
) {
  const params = await props.params;
  return handleRequest(request, params.path);
}

/**
 * Rewrite Set-Cookie headers for local development.
 * When proxying to a remote backend, cookies may have Domain attributes
 * that don't match localhost, causing the browser to reject them.
 * This function strips Domain and adjusts Secure for localhost.
 */
function rewriteCookiesForLocalhost(headers: Headers): Headers {
  const newHeaders = new Headers();

  headers.forEach((value, key) => {
    if (key.toLowerCase() === "set-cookie") {
      // Strip Domain attribute and adjust Secure for localhost
      const rewritten = value
        // Remove Domain=... attribute (case-insensitive)
        .replace(/;\s*Domain=[^;]*/gi, "")
        // For localhost, we can't use Secure (unless using HTTPS)
        .replace(/;\s*Secure/gi, "")
        // SameSite=None requires Secure, so change to Lax for localhost
        .replace(/;\s*SameSite=None/gi, "; SameSite=Lax");
      newHeaders.append(key, rewritten);
    } else {
      newHeaders.append(key, value);
    }
  });

  return newHeaders;
}

async function handleRequest(request: NextRequest, path: string[]) {
  const isDevelopment = process.env.NODE_ENV === "development";

  if (!isDevelopment && process.env.OVERRIDE_API_PRODUCTION !== "true") {
    return NextResponse.json(
      {
        message:
          "This API is only available in development mode. In production, something else (e.g. nginx) should handle this.",
      },
      { status: 404 }
    );
  }

  try {
    const backendUrl = new URL(`${INTERNAL_URL}/${path.join("/")}`);

    // Get the URL parameters from the request
    const urlParams = new URLSearchParams(request.url.split("?")[1]);

    // Append the URL parameters to the backend URL
    urlParams.forEach((value, key) => {
      backendUrl.searchParams.append(key, value);
    });

    const headers = new Headers(request.headers);

    const response = await fetch(backendUrl, {
      method: request.method,
      headers: headers,
      body: request.body,
      signal: request.signal,
      // @ts-ignore
      duplex: "half",
    });

    // In development, rewrite Set-Cookie headers so they work for localhost
    // This allows logging in through the local frontend against a remote backend
    const isRemoteBackend =
      !INTERNAL_URL.includes("localhost") &&
      !INTERNAL_URL.includes("127.0.0.1");
    const responseHeaders =
      isDevelopment && isRemoteBackend
        ? rewriteCookiesForLocalhost(response.headers)
        : response.headers;

    // Check if the response is a stream
    if (
      response.headers.get("Transfer-Encoding") === "chunked" ||
      response.headers.get("Content-Type")?.includes("stream")
    ) {
      // If it's a stream, create a TransformStream to pass the data through
      const { readable, writable } = new TransformStream();
      response.body?.pipeTo(writable);

      return new NextResponse(readable, {
        status: response.status,
        headers: responseHeaders,
      });
    } else {
      return new NextResponse(response.body, {
        status: response.status,
        headers: responseHeaders,
      });
    }
  } catch (error: unknown) {
    console.error("Proxy error:", error);
    return NextResponse.json(
      {
        message: "Proxy error",
        error:
          error instanceof Error ? error.message : "An unknown error occurred",
      },
      { status: 500 }
    );
  }
}
