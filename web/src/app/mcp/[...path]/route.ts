import { MCP_INTERNAL_URL } from "@/lib/constants";
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

async function handleRequest(request: NextRequest, path: string[]) {
  if (
    process.env.NODE_ENV !== "development" &&
    // NOTE: Set this environment variable to 'true' for preview environments
    // Where you want finer-grained control over MCP access
    process.env.OVERRIDE_API_PRODUCTION !== "true"
  ) {
    return NextResponse.json(
      {
        message:
          "This MCP proxy is only available in development mode. In production, something else (e.g. nginx) should handle this.",
      },
      { status: 404 }
    );
  }

  try {
    const mcpUrl = new URL(`${MCP_INTERNAL_URL}/${path.join("/")}`);

    // Get the URL parameters from the request
    const urlParams = new URLSearchParams(request.url.split("?")[1]);

    // Append the URL parameters to the MCP URL
    urlParams.forEach((value, key) => {
      mcpUrl.searchParams.append(key, value);
    });

    const response = await fetch(mcpUrl, {
      method: request.method,
      headers: request.headers,
      body: request.body,
      signal: request.signal,
      // @ts-ignore
      duplex: "half",
    });

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
        headers: response.headers,
      });
    } else {
      return new NextResponse(response.body, {
        status: response.status,
        headers: response.headers,
      });
    }
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
}
