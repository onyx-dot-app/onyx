/**
 * API client for flows.
 *
 * Read paths go through `useSWR(key, errorHandlingFetcher)` in the component
 * that needs them; the functions here are the mutations. Everything routes
 * through the frontend proxy at `/api/...` rather than the backend directly.
 *
 * Each call throws on non-2xx with the server's `detail` when there is one,
 * because a flow spec is rejected with a message worth showing verbatim —
 * "node 'notify' points at undefined node 'summarise'" tells the author
 * exactly what to fix.
 */

import { FLOWS_API_BASE } from "@/app/flows/constants";
import type {
  FlowDecision,
  FlowDetail,
  FlowSpec,
  FlowStatus,
  FlowTrigger,
  JsonObject,
  RunDetail,
  RunSummary,
  TriggerDefinition,
} from "@/app/flows/types";
import type { ErrorResponseBody } from "@/lib/fetcher";

async function readError(res: Response, fallback: string): Promise<never> {
  let detail: string | undefined;
  try {
    const body: ErrorResponseBody | null = await res.json();
    detail = body?.detail;
  } catch {
    // A non-JSON error body is not worth a second failure mode.
  }
  throw new Error(detail || `${fallback} (HTTP ${res.status})`);
}

/** Every body this client sends, so nothing crosses the boundary unparsed. */
type RequestBody =
  | { name: string; description?: string | null; spec: FlowSpec }
  | { name?: string; description?: string | null; spec?: FlowSpec }
  | { status: FlowStatus }
  | { triggers: TriggerDefinition[] }
  | { payload: JsonObject | null }
  | { node_id: string; decision: FlowDecision; comment: string | null };

async function send<T>(
  path: string,
  method: string,
  fallback: string,
  body?: RequestBody
): Promise<T> {
  const res = await fetch(`${FLOWS_API_BASE}${path}`, {
    method,
    headers:
      body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) await readError(res, fallback);
  // SAFETY: `readError` throws on every non-2xx, so anything reaching here is
  // a success body, and each caller names the shape its endpoint returns.
  return (await res.json()) as T;
}

export async function createFlow(input: {
  name: string;
  description?: string | null;
  spec: FlowSpec;
}): Promise<FlowDetail> {
  return send<FlowDetail>("", "POST", "Could not create the flow", input);
}

export async function updateFlow(
  flowId: string,
  input: { name?: string; description?: string | null; spec?: FlowSpec }
): Promise<FlowDetail> {
  return send<FlowDetail>(
    `/${flowId}`,
    "PATCH",
    "Could not save the flow",
    input
  );
}

export async function deleteFlow(flowId: string): Promise<void> {
  const res = await fetch(`${FLOWS_API_BASE}/${flowId}`, { method: "DELETE" });
  if (!res.ok) await readError(res, "Could not delete the flow");
}

export async function publishFlow(flowId: string): Promise<FlowDetail> {
  return send<FlowDetail>(
    `/${flowId}/publish`,
    "POST",
    "Could not publish the flow"
  );
}

export async function setFlowStatus(
  flowId: string,
  status: FlowStatus
): Promise<FlowDetail> {
  return send<FlowDetail>(
    `/${flowId}/status`,
    "POST",
    "Could not change the flow status",
    { status }
  );
}

export async function replaceTriggers(
  flowId: string,
  triggers: TriggerDefinition[]
): Promise<FlowTrigger[]> {
  return send<FlowTrigger[]>(
    `/${flowId}/triggers`,
    "PUT",
    "Could not save the triggers",
    { triggers }
  );
}

/**
 * Answer an approval step a run is parked on.
 *
 * Returns the run as it stands the moment the decision lands, which is back
 * to QUEUED rather than finished — the worker picks it up from there.
 */
export async function submitDecision(
  flowId: string,
  runId: string,
  input: { nodeId: string; decision: FlowDecision; comment?: string | null }
): Promise<RunDetail> {
  return send<RunDetail>(
    `/${flowId}/runs/${runId}/decision`,
    "POST",
    "Could not record the decision",
    {
      node_id: input.nodeId,
      decision: input.decision,
      comment: input.comment ?? null,
    }
  );
}

export async function startRun(
  flowId: string,
  options: { test: boolean; payload?: JsonObject | null }
): Promise<RunSummary> {
  const query = options.test ? "?test=true" : "";
  return send<RunSummary>(
    `/${flowId}/run${query}`,
    "POST",
    "Could not start the run",
    { payload: options.payload ?? null }
  );
}
