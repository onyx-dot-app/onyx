"use client";

import { useTranslations } from "next-intl";
import {
  Button,
  InputKeyValue,
  type KeyValue,
  InputSingleSelect,
  InputTextArea,
  InputTypeIn,
  Text,
} from "@opal/components";
import { InputVertical } from "@opal/layouts";
import { SvgTrash } from "@opal/icons";
import { cn } from "@opal/utils";
import { visualFor } from "@/app/flows/components/nodeVisuals";
import { UNARY_OPERATORS } from "@/app/flows/types";
import type {
  AiNode,
  CodeNode,
  ConditionNode,
  ConditionOperator,
  FlowNode,
  HttpNode,
  HttpMethod,
  HumanNode,
  LoopNode,
  TransformNode,
} from "@/app/flows/types";

const HTTP_METHODS: readonly HttpMethod[] = [
  "GET",
  "POST",
  "PUT",
  "PATCH",
  "DELETE",
];

const OPERATORS: readonly ConditionOperator[] = [
  "eq",
  "ne",
  "gt",
  "gte",
  "lt",
  "lte",
  "contains",
  "not_contains",
  "is_empty",
  "is_not_empty",
];

export interface NodeInspectorProps {
  node: FlowNode;
  /** True for the spec's entry node, which cannot be deleted from here. */
  isStart: boolean;
  canDelete: boolean;
  onChange: (node: FlowNode) => void;
  onDelete: (nodeId: string) => void;
  className?: string;
}

/**
 * Configuration for the selected node.
 *
 * Every field writes straight through `onChange`, so the canvas redraws as
 * you type — renaming a node moves its label immediately, and pointing an
 * edge somewhere new re-lays the graph. There is no separate apply step to
 * forget.
 */
export function NodeInspector({
  node,
  isStart,
  canDelete,
  onChange,
  onDelete,
  className,
}: NodeInspectorProps) {
  const t = useTranslations("flows.inspector");
  const visual = visualFor(node.kind);
  const Icon = visual.icon;

  return (
    <aside
      data-testid="node-inspector"
      className={cn(
        "flex flex-col gap-4 p-4 overflow-y-auto",
        "bg-background-neutral-00 border-s border-border-01",
        className
      )}
    >
      <div className="flex flex-row items-center gap-2">
        <span
          className={cn(
            "flex items-center justify-center w-7 h-7 rounded-08 shrink-0",
            visual.chipClassName
          )}
        >
          <Icon size={16} className={visual.iconClassName} />
        </span>
        <Text font="main-ui-action" color="text-05">
          {t(`kind.${node.kind}`)}
        </Text>
      </div>

      <InputVertical withLabel title={t("fields.name")}>
        <InputTypeIn
          value={node.name}
          onChange={(event) => onChange({ ...node, name: event.target.value })}
        />
      </InputVertical>

      {node.kind === "HTTP" ? (
        <HttpFields node={node} onChange={onChange} />
      ) : null}
      {node.kind === "TRANSFORM" ? (
        <TransformFields node={node} onChange={onChange} />
      ) : null}
      {node.kind === "CONDITION" ? (
        <ConditionFields node={node} onChange={onChange} />
      ) : null}
      {node.kind === "AI" ? <AiFields node={node} onChange={onChange} /> : null}
      {node.kind === "HUMAN" ? (
        <HumanFields node={node} onChange={onChange} />
      ) : null}
      {node.kind === "CODE" ? (
        <CodeFields node={node} onChange={onChange} />
      ) : null}
      {node.kind === "LOOP" ? (
        <LoopFields node={node} onChange={onChange} />
      ) : null}

      {canFanOut(node) ? (
        <InputVertical
          withLabel
          title={t("fields.forEach")}
          description={t("fields.forEachHelp")}
          suffix="optional"
        >
          <InputTypeIn
            value={node.for_each ?? ""}
            placeholder={t("placeholder.forEach")}
            onChange={(event) =>
              onChange({
                ...node,
                for_each: event.target.value === "" ? null : event.target.value,
              })
            }
          />
        </InputVertical>
      ) : null}

      <InputVertical withLabel title={t("fields.onError")}>
        <InputSingleSelect
          value={node.on_error}
          onValueChange={(value) =>
            onChange({ ...node, on_error: value === "skip" ? "skip" : "stop" })
          }
        >
          <InputSingleSelect.Trigger />
          <InputSingleSelect.Content>
            <InputSingleSelect.Item value="stop">
              {t("onError.stop")}
            </InputSingleSelect.Item>
            <InputSingleSelect.Item value="skip">
              {t("onError.skip")}
            </InputSingleSelect.Item>
          </InputSingleSelect.Content>
        </InputSingleSelect>
      </InputVertical>

      <InputVertical
        withLabel
        title={t("fields.retries")}
        description={t("fields.retriesHelp")}
      >
        <InputTypeIn
          type="number"
          min={1}
          max={4}
          value={String(node.retry.max_attempts)}
          onChange={(event) =>
            onChange({
              ...node,
              retry: {
                ...node.retry,
                max_attempts: clampAttempts(event.target.value),
              },
            })
          }
        />
      </InputVertical>

      {canDelete && !isStart ? (
        <Button
          variant="danger"
          prominence="tertiary"
          icon={SvgTrash}
          onClick={() => onDelete(node.id)}
        >
          {t("actions.delete")}
        </Button>
      ) : null}
    </aside>
  );
}

/**
 * Whether this kind may fan out.
 *
 * The server rejects `for_each` on a branching node — per-item branching has
 * no answer once the items disagree — so the field is not offered rather than
 * offered and then refused on save.
 */
function canFanOut(node: FlowNode): boolean {
  return node.kind !== "CONDITION" && node.kind !== "HUMAN";
}

/** Keep the attempt count inside what the server will accept. */
function clampAttempts(raw: string): number {
  const parsed = Number.parseInt(raw, 10);
  if (Number.isNaN(parsed)) return 1;
  return Math.min(4, Math.max(1, parsed));
}

/**
 * `InputKeyValue` works in ordered pairs; headers and transform fields are
 * objects on the wire. Converting at the edge keeps the spec shape honest
 * and the duplicate-key handling the component's problem, not ours.
 */
function toPairs(record: Record<string, string>): KeyValue[] {
  return Object.entries(record).map(([key, value]) => ({ key, value }));
}

function toRecord(items: KeyValue[]): Record<string, string> {
  return Object.fromEntries(
    items
      .filter((item) => item.key !== "")
      .map((item) => [item.key, item.value])
  );
}

interface FieldProps<T extends FlowNode> {
  node: T;
  onChange: (node: FlowNode) => void;
}

function HttpFields({ node, onChange }: FieldProps<HttpNode>) {
  const t = useTranslations("flows.inspector");

  return (
    <>
      <InputVertical withLabel title={t("fields.method")}>
        <InputSingleSelect
          value={node.method}
          onValueChange={(value) =>
            onChange({ ...node, method: asHttpMethod(value) })
          }
        >
          <InputSingleSelect.Trigger />
          <InputSingleSelect.Content>
            {HTTP_METHODS.map((method) => (
              <InputSingleSelect.Item key={method} value={method}>
                {method}
              </InputSingleSelect.Item>
            ))}
          </InputSingleSelect.Content>
        </InputSingleSelect>
      </InputVertical>

      <InputVertical
        withLabel
        title={t("fields.url")}
        description={t("fields.urlHelp")}
      >
        <InputTypeIn
          value={node.url}
          onChange={(event) => onChange({ ...node, url: event.target.value })}
        />
      </InputVertical>

      <InputVertical withLabel title={t("fields.headers")} suffix="optional">
        <InputKeyValue
          items={toPairs(node.headers)}
          onChange={(items) => onChange({ ...node, headers: toRecord(items) })}
        />
      </InputVertical>

      <InputVertical
        withLabel
        title={t("fields.resultPath")}
        description={t("fields.resultPathHelp")}
        suffix="optional"
      >
        <InputTypeIn
          value={node.result_path ?? ""}
          placeholder={t("placeholder.resultPath")}
          onChange={(event) =>
            onChange({
              ...node,
              result_path:
                event.target.value === "" ? null : event.target.value,
            })
          }
        />
      </InputVertical>
    </>
  );
}

function TransformFields({ node, onChange }: FieldProps<TransformNode>) {
  const t = useTranslations("flows.inspector");

  return (
    <InputVertical
      withLabel
      title={t("fields.transformFields")}
      description={t("fields.transformFieldsHelp")}
    >
      <InputKeyValue
        keyTitle={t("fields.fieldName")}
        valueTitle={t("fields.fieldExpression")}
        valuePlaceholder={t("placeholder.fieldExpression")}
        mode="fixed-line"
        items={toPairs(node.fields)}
        onChange={(items) => onChange({ ...node, fields: toRecord(items) })}
      />
    </InputVertical>
  );
}

function ConditionFields({ node, onChange }: FieldProps<ConditionNode>) {
  const t = useTranslations("flows.inspector");
  const needsRight = !UNARY_OPERATORS.includes(node.operator);

  return (
    <>
      <InputVertical withLabel title={t("fields.left")}>
        <InputTypeIn
          value={node.left}
          placeholder={t("placeholder.left")}
          onChange={(event) => onChange({ ...node, left: event.target.value })}
        />
      </InputVertical>

      <InputVertical withLabel title={t("fields.operator")}>
        <InputSingleSelect
          value={node.operator}
          onValueChange={(value) => {
            const operator = asOperator(value);
            onChange({
              ...node,
              operator,
              // Clearing the comparison value when it stops applying keeps a
              // stale one from reappearing if the operator changes back.
              right: UNARY_OPERATORS.includes(operator)
                ? null
                : (node.right ?? ""),
            });
          }}
        >
          <InputSingleSelect.Trigger />
          <InputSingleSelect.Content>
            {OPERATORS.map((operator) => (
              <InputSingleSelect.Item key={operator} value={operator}>
                {t(`operator.${operator}`)}
              </InputSingleSelect.Item>
            ))}
          </InputSingleSelect.Content>
        </InputSingleSelect>
      </InputVertical>

      {needsRight ? (
        <InputVertical withLabel title={t("fields.right")}>
          <InputTypeIn
            value={node.right ?? ""}
            onChange={(event) =>
              onChange({ ...node, right: event.target.value })
            }
          />
        </InputVertical>
      ) : null}
    </>
  );
}

function AiFields({ node, onChange }: FieldProps<AiNode>) {
  const t = useTranslations("flows.inspector");

  return (
    <>
      <InputVertical
        withLabel
        title={t("fields.prompt")}
        description={t("fields.promptHelp")}
      >
        <InputTextArea
          value={node.prompt}
          rows={5}
          onChange={(event) =>
            onChange({ ...node, prompt: event.target.value })
          }
        />
      </InputVertical>

      <InputVertical
        withLabel
        title={t("fields.outputFields")}
        description={t("fields.outputFieldsHelp")}
        suffix="optional"
      >
        <InputKeyValue
          keyTitle={t("fields.fieldName")}
          valueTitle={t("fields.fieldType")}
          valuePlaceholder={t("placeholder.fieldType")}
          items={node.output_fields.map((field) => ({
            key: field.name,
            value: field.type,
          }))}
          onChange={(items) =>
            onChange({
              ...node,
              output_fields: items.map((item) => ({
                name: item.key,
                type: asFieldType(item.value),
                description: "",
              })),
            })
          }
        />
      </InputVertical>
    </>
  );
}

function HumanFields({ node, onChange }: FieldProps<HumanNode>) {
  const t = useTranslations("flows.inspector");

  return (
    <>
      <InputVertical
        withLabel
        title={t("fields.question")}
        description={t("fields.questionHelp")}
      >
        <InputTextArea
          value={node.question}
          rows={3}
          placeholder={t("placeholder.question")}
          onChange={(event) =>
            onChange({ ...node, question: event.target.value })
          }
        />
      </InputVertical>

      <InputVertical
        withLabel
        title={t("fields.assignee")}
        description={t("fields.assigneeHelp")}
        suffix="optional"
      >
        <InputTypeIn
          value={node.assignee ?? ""}
          placeholder={t("placeholder.assignee")}
          onChange={(event) =>
            onChange({
              ...node,
              assignee: event.target.value === "" ? null : event.target.value,
            })
          }
        />
      </InputVertical>

      {node.on_reject.length === 0 ? (
        <Text font="main-ui-muted" color="text-03">
          {t("fields.rejectEndsRun")}
        </Text>
      ) : null}
    </>
  );
}

function CodeFields({ node, onChange }: FieldProps<CodeNode>) {
  const t = useTranslations("flows.inspector");

  return (
    <InputVertical
      withLabel
      title={t("fields.code")}
      description={t("fields.codeHelp")}
    >
      <InputTextArea
        value={node.code}
        rows={10}
        // Nothing in a snippet is a word, and a red squiggle under every
        // identifier makes the field harder to read than it needs to be.
        spellCheck={false}
        onChange={(event) => onChange({ ...node, code: event.target.value })}
      />
    </InputVertical>
  );
}

function LoopFields({ node, onChange }: FieldProps<LoopNode>) {
  const t = useTranslations("flows.inspector");

  return (
    <>
      <InputVertical
        withLabel
        title={t("fields.over")}
        description={t("fields.overHelp")}
      >
        <InputTypeIn
          value={node.over}
          placeholder={t("placeholder.over")}
          onChange={(event) => onChange({ ...node, over: event.target.value })}
        />
      </InputVertical>

      <InputVertical
        withLabel
        title={t("fields.batchSize")}
        description={t("fields.batchSizeHelp")}
      >
        <InputTypeIn
          type="number"
          min={1}
          max={200}
          value={String(node.batch_size)}
          onChange={(event) =>
            onChange({
              ...node,
              batch_size: clampBatchSize(event.target.value),
            })
          }
        />
      </InputVertical>
    </>
  );
}

/** Keep the batch size inside what the server will accept. */
function clampBatchSize(raw: string): number {
  const parsed = Number.parseInt(raw, 10);
  if (Number.isNaN(parsed)) return 1;
  return Math.min(200, Math.max(1, parsed));
}

function asHttpMethod(value: string): HttpMethod {
  const found = HTTP_METHODS.find((method) => method === value);
  return found ?? "GET";
}

function asOperator(value: string): ConditionOperator {
  const found = OPERATORS.find((operator) => operator === value);
  return found ?? "eq";
}

function asFieldType(value: string): AiNode["output_fields"][number]["type"] {
  switch (value) {
    case "number":
    case "boolean":
    case "list":
      return value;
    default:
      return "text";
  }
}
