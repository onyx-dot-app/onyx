/**
 * Service layer for MCP (Model Context Protocol) related API calls
 */

import * as yup from "yup";
import { FetchError } from "@/lib/fetcher";
import type { MCPProbeProgress } from "@/lib/mcp/types";
import {
  MCPOAuthDiscovery,
  MCPTransportType,
  MCPSetupProbeResult,
} from "@/lib/mcp/types";

const probeTransport = yup
  .mixed<MCPTransportType.STREAMABLE_HTTP | MCPTransportType.SSE>()
  .oneOf([MCPTransportType.STREAMABLE_HTTP, MCPTransportType.SSE])
  .defined();
const progressSchema = yup.object({
  type: yup.mixed<"progress">().oneOf(["progress"]).defined(),
  stage: yup
    .mixed<MCPProbeProgress["stage"]>()
    .oneOf(["contacting_server", "authentication"])
    .defined(),
  state: yup
    .mixed<MCPProbeProgress["state"]>()
    .oneOf(["pending", "success", "error"])
    .defined(),
});
// oxlint-disable-next-line anti-slop/no-unknown-parameters -- Validates untrusted probe JSON at the stream boundary.
function parseProbeResult(value: unknown): MCPSetupProbeResult {
  const { kind } = yup
    .object({ kind: yup.string().defined() })
    .validateSync(value, { strict: true });
  switch (kind) {
    case "public":
      return yup
        .object({
          kind: yup.mixed<"public">().oneOf(["public"]).defined(),
          transport: probeTransport,
          tool_count: yup.number().integer().min(0).defined(),
          server_name: yup.string().defined(),
        })
        .validateSync(value, { strict: true });
    case "oauth":
      return yup
        .object({
          kind: yup.mixed<"oauth">().oneOf(["oauth"]).defined(),
          transport: probeTransport.nullable(),
          discovery: yup
            .object({
              status: yup
                .mixed<MCPOAuthDiscovery["status"]>()
                .oneOf(["metadata_found", "metadata_missing", "unreachable"])
                .defined(),
              supports_automatic_registration: yup
                .boolean()
                .nullable()
                .defined(),
              supports_client_metadata: yup.boolean().nullable().defined(),
              authorization_endpoint: yup.string().nullable().defined(),
              token_endpoint: yup.string().nullable().defined(),
            })
            .defined(),
        })
        .validateSync(value, { strict: true });
    case "auth_unknown":
      return yup
        .object({
          kind: yup.mixed<"auth_unknown">().oneOf(["auth_unknown"]).defined(),
          transport: probeTransport.nullable(),
        })
        .validateSync(value, { strict: true });
    case "unreachable":
      return yup
        .object({
          kind: yup.mixed<"unreachable">().oneOf(["unreachable"]).defined(),
          reason: yup
            .mixed<"blocked" | "connection_failed">()
            .oneOf(["blocked", "connection_failed"])
            .defined(),
        })
        .validateSync(value, { strict: true });
    default:
      throw new Error("Invalid MCP probe result");
  }
}

export async function streamMCPServerProbe(
  serverUrl: string,
  onProgress: (event: MCPProbeProgress) => void,
  signal?: AbortSignal
): Promise<MCPSetupProbeResult> {
  const response = await fetch("/api/admin/mcp/probe", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ server_url: serverUrl }),
    signal,
  });
  if (!response.ok || !response.body)
    throw new FetchError("MCP probe failed", response.status, null);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: MCPSetupProbeResult | undefined;
  function consume(line: string) {
    if (!line.trim()) return;
    const value: unknown = JSON.parse(line);
    const event = yup
      .object({
        type: yup
          .mixed<"progress" | "result">()
          .oneOf(["progress", "result"])
          .defined(),
      })
      .validateSync(value, { strict: true });
    if (result) throw new Error("Unexpected MCP probe event");
    if (event.type === "progress")
      onProgress(progressSchema.validateSync(value, { strict: true }));
    else
      result = parseProbeResult(
        yup
          .object({ result: yup.mixed().defined() })
          .validateSync(value, { strict: true }).result
      );
  }
  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      if (buffer.length > 65536) throw new Error("Invalid MCP probe stream");
      let newline: number;
      while ((newline = buffer.indexOf("\n")) !== -1) {
        consume(buffer.slice(0, newline));
        buffer = buffer.slice(newline + 1);
      }
      if (done) break;
    }
    consume(buffer);
    if (!result) throw new Error("Incomplete MCP probe stream");
    return result;
  } finally {
    await reader.cancel();
    reader.releaseLock();
  }
}
