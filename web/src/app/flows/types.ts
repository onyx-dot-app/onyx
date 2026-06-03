/**
 * Shapes returned by the flows API.
 *
 * Mirrors `backend/onyx/flows/models.py` and
 * `backend/onyx/server/features/flows/models.py`. The node union is
 * discriminated on `kind`, the same way the backend discriminates its
 * Pydantic union, so narrowing works identically on both sides.
 */

export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

export type JsonObject = { [key: string]: JsonValue };

export type FlowStatus = "ACTIVE" | "PAUSED";
export type FlowNodeKind = "HTTP" | "TRANSFORM" | "CONDITION" | "AI";
export type FlowTriggerKind = "SCHEDULE" | "WEBHOOK" | "MANUAL";
export type FlowTriggerSource = "SCHEDULE" | "WEBHOOK" | "MANUAL" | "TEST";

export type FlowRunStatus =
  | "QUEUED"
  | "RUNNING"
  | "SUCCEEDED"
  | "FAILED"
  | "SKIPPED";

export type FlowNodeRunStatus = "RUNNING" | "SUCCEEDED" | "FAILED" | "SKIPPED";

export type ConditionOperator =
  | "eq"
  | "ne"
  | "gt"
  | "gte"
  | "lt"
  | "lte"
  | "contains"
  | "not_contains"
  | "is_empty"
  | "is_not_empty";

/** Operators that compare against nothing, so `right` is hidden for them. */
export const UNARY_OPERATORS: readonly ConditionOperator[] = [
  "is_empty",
  "is_not_empty",
];

export type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export interface RetryPolicy {
  max_attempts: number;
  backoff_seconds: number;
}

interface NodeBase {
  id: string;
  name: string;
  next: string[];
  for_each: string | null;
  on_error: "stop" | "skip";
  retry: RetryPolicy;
}

export interface HttpNode extends NodeBase {
  kind: "HTTP";
  method: HttpMethod;
  url: string;
  headers: Record<string, string>;
  query: Record<string, string>;
  body: JsonValue;
  timeout_seconds: number;
  result_path: string | null;
  fail_on_error_status: boolean;
}

export interface TransformNode extends NodeBase {
  kind: "TRANSFORM";
  fields: Record<string, string>;
}

export interface ConditionNode extends NodeBase {
  kind: "CONDITION";
  left: string;
  operator: ConditionOperator;
  right: string | null;
  on_true: string[];
  on_false: string[];
}

export interface AiOutputField {
  name: string;
  type: "text" | "number" | "boolean" | "list";
  description: string;
}

export interface AiNode extends NodeBase {
  kind: "AI";
  prompt: string;
  output_fields: AiOutputField[];
  timeout_seconds: number;
}

export type FlowNode = HttpNode | TransformNode | ConditionNode | AiNode;

export interface FlowSpec {
  spec_version: 1;
  start: string;
  nodes: FlowNode[];
}

export interface FlowTrigger {
  id: string;
  kind: FlowTriggerKind;
  config: JsonObject;
  enabled: boolean;
  next_run_at: string | null;
  /** Returned only by the response that mints it. */
  webhook_secret: string | null;
}

export interface FlowSummary {
  id: string;
  name: string;
  description: string | null;
  status: FlowStatus;
  published_version: number | null;
  node_count: number;
  triggers: FlowTrigger[];
  created_at: string;
  updated_at: string;
}

export interface FlowDetail extends FlowSummary {
  spec: FlowSpec;
  has_unpublished_changes: boolean;
}

export interface NodeRun {
  node_id: string;
  kind: FlowNodeKind;
  status: FlowNodeRunStatus;
  item_index: number;
  attempt: number;
  input: JsonObject | null;
  output: JsonValue;
  error_class: string | null;
  error_detail: string | null;
  started_at: string;
  finished_at: string | null;
}

export interface RunSummary {
  id: string;
  flow_id: string;
  status: FlowRunStatus;
  trigger_source: FlowTriggerSource;
  skip_reason: string | null;
  error_class: string | null;
  error_detail: string | null;
  started_at: string;
  finished_at: string | null;
}

export interface RunDetail extends RunSummary {
  trigger_payload: JsonObject | null;
  node_runs: NodeRun[];
}

export interface TriggerDefinition {
  kind: FlowTriggerKind;
  config: JsonObject;
  enabled: boolean;
}
