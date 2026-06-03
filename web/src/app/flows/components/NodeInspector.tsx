"use client";

import { useTranslations } from "next-intl";
import {
  Button,
  InputCheckbox,
  InputKeyValue,
  type KeyValue,
  InputSingleSelect,
  InputTextArea,
  InputTypeIn,
  Text,
} from "@opal/components";
import { InputVertical } from "@opal/layouts";
import { SvgPlus, SvgTrash } from "@opal/icons";
import { cn } from "@opal/utils";
import { visualFor } from "@/app/flows/components/nodeVisuals";
import { UNARY_OPERATORS } from "@/app/flows/types";
import type { JsonValue } from "@/app/flows/types";
import type {
  AiNode,
  CodeNode,
  FlowNodeKind,
  ConditionNode,
  ConditionOperator,
  DelayNode,
  FilterNode,
  MergeMode,
  MergeNode,
  FlowNode,
  HttpNode,
  HttpMethod,
  HumanNode,
  LoopNode,
  ParallelNode,
  RetryNode,
  ScheduleNode,
  SplitNode,
  SwitchCase,
  SwitchNode,
  TransformNode,
  WebhookNode,
} from "@/app/flows/types";

const HTTP_METHODS: readonly HttpMethod[] = [
  "GET",
  "POST",
  "PUT",
  "PATCH",
  "DELETE",
];

/** The line between a delay that sleeps and one that parks the run. */
const INLINE_DELAY_SECONDS = 60;

/** Thirty days, matching the server's ceiling. */
const MAX_DELAY_SECONDS = 30 * 24 * 60 * 60;

/** Matching the server's ceilings. */
const MAX_SWITCH_CASES = 10;
const MAX_PARALLEL_CALLS = 10;
const MAX_PAUSE_SECONDS = 60;

/**
 * The picker value for "this branch ends here".
 *
 * Radix Select refuses an empty string as an item value, and a node id can
 * never start with an underscore, so this cannot collide with a real step.
 */
const ENDS_HERE = "__end__";

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
  /** The flow's key, shown on a webhook step so it can be copied into the
   *  receiving system. Null while the flow is still loading. */
  webhookSigningSecret?: string | null;
  /** Steps that lead to this one, which a merge may name as sources. */
  mergeCandidates?: readonly string[];
  /** Steps a switch case may lead to: everything but this one and its
   *  ancestors, since either would close a loop. */
  branchTargets?: readonly string[];
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
  webhookSigningSecret,
  mergeCandidates,
  branchTargets,
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
      {node.kind === "RETRY" ? (
        <RetryFields node={node} onChange={onChange} />
      ) : null}
      {node.kind === "SPLIT" ? (
        <SplitFields node={node} onChange={onChange} />
      ) : null}
      {node.kind === "SCHEDULE" ? (
        <ScheduleFields node={node} onChange={onChange} />
      ) : null}
      {node.kind === "MERGE" ? (
        <MergeFields
          node={node}
          candidates={mergeCandidates ?? []}
          onChange={onChange}
        />
      ) : null}
      {node.kind === "DELAY" ? (
        <DelayFields node={node} onChange={onChange} />
      ) : null}
      {node.kind === "FILTER" ? (
        <FilterFields node={node} onChange={onChange} />
      ) : null}
      {node.kind === "PARALLEL" ? (
        <ParallelFields node={node} onChange={onChange} />
      ) : null}
      {node.kind === "SWITCH" ? (
        <SwitchFields
          node={node}
          targets={branchTargets ?? []}
          onChange={onChange}
        />
      ) : null}
      {node.kind === "WEBHOOK" ? (
        <WebhookFields
          node={node}
          signingSecret={webhookSigningSecret ?? null}
          onChange={onChange}
        />
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
              onChange(
                event.target.value === ""
                  ? // A pause only means anything between items, and the
                    // server refuses one on a step that runs once.
                    { ...node, for_each: null, pause_seconds: 0 }
                  : { ...node, for_each: event.target.value }
              )
            }
          />
        </InputVertical>
      ) : null}

      {canFanOut(node) && node.for_each !== null ? (
        <InputVertical
          withLabel
          title={t("fields.pauseSeconds")}
          description={t("fields.pauseSecondsHelp")}
          suffix="optional"
        >
          <InputTypeIn
            type="number"
            min={0}
            max={MAX_PAUSE_SECONDS}
            value={String(node.pause_seconds ?? 0)}
            onChange={(event) =>
              onChange({
                ...node,
                pause_seconds: clampPause(event.target.value),
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
 * Kinds the server refuses `for_each` on.
 *
 * Each has its own reason — a branch has no answer once the items disagree,
 * a wait would be the same wall clock spent N times over, a merge has one
 * output per source already, a parallel step fans out on its own — but the
 * rule for the editor is the same: do not offer a field that only gets
 * refused on save.
 *
 * Mirrors the `_no_fan_out` validators in `backend/onyx/flows/models.py`.
 */
const NEVER_FANS_OUT: readonly FlowNodeKind[] = [
  "CONDITION",
  "SWITCH",
  "HUMAN",
  "DELAY",
  "SCHEDULE",
  "MERGE",
  "PARALLEL",
];

function canFanOut(node: FlowNode): boolean {
  return !NEVER_FANS_OUT.includes(node.kind);
}

/** Keep the pause between items inside what the server will accept. */
function clampPause(raw: string): number {
  const parsed = Number.parseFloat(raw);
  if (Number.isNaN(parsed)) return 0;
  return Math.min(MAX_PAUSE_SECONDS, Math.max(0, parsed));
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

function HttpFields<T extends HttpNode | ParallelNode>({
  node,
  onChange,
}: FieldProps<T>) {
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

function ParallelFields({ node, onChange }: FieldProps<ParallelNode>) {
  const t = useTranslations("flows.inspector");

  return (
    <>
      <InputVertical
        withLabel
        title={t("fields.parallelOver")}
        description={t("fields.parallelOverHelp")}
      >
        <InputTypeIn
          value={node.over}
          placeholder={t("placeholder.over")}
          onChange={(event) => onChange({ ...node, over: event.target.value })}
        />
      </InputVertical>

      <HttpFields node={node} onChange={onChange} />

      <InputVertical
        withLabel
        title={t("fields.concurrency")}
        description={t("fields.concurrencyHelp")}
      >
        <InputTypeIn
          type="number"
          min={1}
          max={MAX_PARALLEL_CALLS}
          value={String(node.concurrency)}
          onChange={(event) =>
            onChange({
              ...node,
              concurrency: clampConcurrency(event.target.value),
            })
          }
        />
      </InputVertical>
    </>
  );
}

/** Keep the calls in flight inside what the server will accept. */
function clampConcurrency(raw: string): number {
  const parsed = Number.parseInt(raw, 10);
  if (Number.isNaN(parsed)) return 1;
  return Math.min(MAX_PARALLEL_CALLS, Math.max(1, parsed));
}

function SwitchFields({
  node,
  targets,
  onChange,
}: FieldProps<SwitchNode> & { targets: readonly string[] }) {
  const t = useTranslations("flows.inspector");

  function updateCase(position: number, change: Partial<SwitchCase>): void {
    onChange({
      ...node,
      cases: node.cases.map((branch, index) =>
        index === position ? { ...branch, ...change } : branch
      ),
    });
  }

  function removeCase(position: number): void {
    onChange({
      ...node,
      cases: node.cases.filter((_, index) => index !== position),
    });
  }

  return (
    <>
      <InputVertical
        withLabel
        title={t("fields.switchValue")}
        description={t("fields.switchValueHelp")}
      >
        <InputTypeIn
          value={node.value}
          placeholder={t("placeholder.switchValue")}
          onChange={(event) => onChange({ ...node, value: event.target.value })}
        />
      </InputVertical>

      <InputVertical
        withLabel
        title={t("fields.switchCases")}
        description={t("fields.switchCasesHelp")}
      >
        <div data-testid="switch-cases" className="flex flex-col gap-3 w-full">
          {node.cases.map((branch, position) => {
            const number = position + 1;
            return (
              // Rows have no identity of their own; the position is what the
              // run history records, so it is the honest key.
              <div key={position} className="flex flex-col gap-1 w-full">
                <Text font="figure-small-label" color="text-03">
                  {t("fields.caseHeading", { number })}
                </Text>
                <div className="flex flex-row items-center gap-1 w-full">
                  <div className="flex-1 min-w-0">
                    <InputTypeIn
                      aria-label={t("fields.caseValue", { number })}
                      value={branch.equals}
                      placeholder={t("placeholder.caseValue")}
                      onChange={(event) =>
                        updateCase(position, { equals: event.target.value })
                      }
                    />
                  </div>
                  <Button
                    variant="default"
                    prominence="tertiary"
                    size="sm"
                    icon={SvgTrash}
                    tooltip={t("actions.removeCase", { number })}
                    aria-label={t("actions.removeCase", { number })}
                    // The server needs one case; a switch with none is a
                    // condition that always says no.
                    disabled={node.cases.length === 1}
                    onClick={() => removeCase(position)}
                  />
                </div>
                <BranchTargetSelect
                  label={t("fields.caseTarget", { number })}
                  value={branch.then}
                  targets={targets}
                  onChange={(then) => updateCase(position, { then })}
                />
              </div>
            );
          })}
        </div>
      </InputVertical>

      {node.cases.length < MAX_SWITCH_CASES ? (
        <Button
          variant="default"
          prominence="secondary"
          size="sm"
          icon={SvgPlus}
          onClick={() =>
            onChange({
              ...node,
              cases: [...node.cases, { equals: "", then: [] }],
            })
          }
        >
          {t("actions.addCase")}
        </Button>
      ) : null}

      <InputVertical withLabel title={t("fields.switchOtherwise")}>
        <BranchTargetSelect
          label={t("fields.switchOtherwise")}
          value={node.otherwise}
          targets={targets}
          onChange={(otherwise) => onChange({ ...node, otherwise })}
        />
      </InputVertical>
    </>
  );
}

interface BranchTargetSelectProps {
  label: string;
  value: readonly string[];
  targets: readonly string[];
  onChange: (targets: string[]) => void;
}

/**
 * Where one branch goes: a step, or nowhere.
 *
 * One destination per branch here. A spec written against the API can give
 * a branch several; picking a new one replaces them all, because choosing a
 * destination is what the picker is for.
 */
function BranchTargetSelect({
  label,
  value,
  targets,
  onChange,
}: BranchTargetSelectProps) {
  const t = useTranslations("flows.inspector");

  return (
    <InputSingleSelect
      value={value[0] ?? ENDS_HERE}
      onValueChange={(picked) => onChange(picked === ENDS_HERE ? [] : [picked])}
    >
      <InputSingleSelect.Trigger aria-label={label} />
      <InputSingleSelect.Content>
        <InputSingleSelect.Item value={ENDS_HERE}>
          {t("fields.branchEnds")}
        </InputSingleSelect.Item>
        {targets.map((target) => (
          <InputSingleSelect.Item key={target} value={target}>
            {target}
          </InputSingleSelect.Item>
        ))}
      </InputSingleSelect.Content>
    </InputSingleSelect>
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

      {/* The pause lives on the step that sends the batches, since that is
          what waits. Said here because this is where people look for it. */}
      <Text font="main-ui-muted" color="text-03">
        {t("fields.loopPauseHint")}
      </Text>
    </>
  );
}

/** Keep the batch size inside what the server will accept. */
function clampBatchSize(raw: string): number {
  const parsed = Number.parseInt(raw, 10);
  if (Number.isNaN(parsed)) return 1;
  return Math.min(200, Math.max(1, parsed));
}

function SplitFields({ node, onChange }: FieldProps<SplitNode>) {
  const t = useTranslations("flows.inspector");

  return (
    <>
      <InputVertical
        withLabel
        title={t("fields.splitValue")}
        description={t("fields.splitValueHelp")}
      >
        <InputTypeIn
          value={node.value}
          placeholder={t("placeholder.splitValue")}
          onChange={(event) => onChange({ ...node, value: event.target.value })}
        />
      </InputVertical>

      <InputVertical
        withLabel
        title={t("fields.separator")}
        description={t("fields.separatorHelp")}
      >
        <InputTypeIn
          value={node.separator}
          onChange={(event) =>
            onChange({ ...node, separator: event.target.value })
          }
        />
      </InputVertical>

      <label className="flex flex-row items-center gap-2 cursor-pointer">
        <InputCheckbox
          checked={node.trim}
          onCheckedChange={(checked) => onChange({ ...node, trim: checked })}
        />
        <Text font="main-ui-body" color="text-04">
          {t("fields.splitTrim")}
        </Text>
      </label>

      <label className="flex flex-row items-center gap-2 cursor-pointer">
        <InputCheckbox
          checked={node.drop_empty}
          onCheckedChange={(checked) =>
            onChange({ ...node, drop_empty: checked })
          }
        />
        <Text font="main-ui-body" color="text-04">
          {t("fields.splitDropEmpty")}
        </Text>
      </label>
    </>
  );
}

function ScheduleFields({ node, onChange }: FieldProps<ScheduleNode>) {
  const t = useTranslations("flows.inspector");

  return (
    <InputVertical
      withLabel
      title={t("fields.cron")}
      description={t("fields.cronHelp")}
    >
      <InputTypeIn
        value={node.cron}
        placeholder={t("placeholder.cron")}
        onChange={(event) => onChange({ ...node, cron: event.target.value })}
      />
    </InputVertical>
  );
}

function MergeFields({
  node,
  candidates,
  onChange,
}: FieldProps<MergeNode> & { candidates: readonly string[] }) {
  const t = useTranslations("flows.inspector");

  function toggle(source: string, checked: boolean): void {
    // Kept in candidate order rather than click order, so the output reads
    // the same way the graph does however it was assembled.
    const chosen = new Set(node.sources);
    if (checked) chosen.add(source);
    else chosen.delete(source);
    onChange({
      ...node,
      sources: candidates.filter((id) => chosen.has(id)),
    });
  }

  return (
    <>
      <InputVertical
        withLabel
        title={t("fields.mergeSources")}
        description={t("fields.mergeSourcesHelp")}
      >
        {candidates.length === 0 ? (
          <Text font="main-ui-muted" color="text-03">
            {t("fields.mergeNoCandidates")}
          </Text>
        ) : (
          <div
            data-testid="merge-sources"
            className="flex flex-col gap-2 w-full"
          >
            {candidates.map((source) => (
              <label
                key={source}
                className="flex flex-row items-center gap-2 cursor-pointer"
              >
                <InputCheckbox
                  checked={node.sources.includes(source)}
                  onCheckedChange={(checked) => toggle(source, checked)}
                />
                <Text font="main-ui-body" color="text-04">
                  {source}
                </Text>
              </label>
            ))}
          </div>
        )}
      </InputVertical>

      {node.sources.length < 2 ? (
        <Text font="main-ui-muted" color="text-03">
          {t("fields.mergeNeedsTwo")}
        </Text>
      ) : null}

      <InputVertical
        withLabel
        title={t("fields.mergeMode")}
        description={t("fields.mergeModeHelp")}
      >
        <InputSingleSelect
          value={node.mode}
          onValueChange={(raw) => onChange({ ...node, mode: asMergeMode(raw) })}
        >
          <InputSingleSelect.Trigger />
          <InputSingleSelect.Content>
            <InputSingleSelect.Item value="combine">
              {t("mergeMode.combine")}
            </InputSingleSelect.Item>
            <InputSingleSelect.Item value="append">
              {t("mergeMode.append")}
            </InputSingleSelect.Item>
          </InputSingleSelect.Content>
        </InputSingleSelect>
      </InputVertical>
    </>
  );
}

function asMergeMode(value: string): MergeMode {
  return value === "append" ? "append" : "combine";
}

function DelayFields({ node, onChange }: FieldProps<DelayNode>) {
  const t = useTranslations("flows.inspector");

  return (
    <>
      <InputVertical
        withLabel
        title={t("fields.waitSeconds")}
        description={t("fields.waitSecondsHelp")}
      >
        <InputTypeIn
          type="number"
          min={0}
          max={MAX_DELAY_SECONDS}
          value={String(node.seconds)}
          onChange={(event) =>
            onChange({ ...node, seconds: clampDelay(event.target.value) })
          }
        />
      </InputVertical>

      <Text font="main-ui-muted" color="text-03">
        {node.seconds > INLINE_DELAY_SECONDS
          ? t("fields.delayParks")
          : t("fields.delayWaits")}
      </Text>
    </>
  );
}

function FilterFields({ node, onChange }: FieldProps<FilterNode>) {
  const t = useTranslations("flows.inspector");
  const needsRight = !UNARY_OPERATORS.includes(node.operator);

  return (
    <>
      <InputVertical
        withLabel
        title={t("fields.filterOver")}
        description={t("fields.filterOverHelp")}
      >
        <InputTypeIn
          value={node.over}
          placeholder={t("placeholder.over")}
          onChange={(event) => onChange({ ...node, over: event.target.value })}
        />
      </InputVertical>

      <InputVertical
        withLabel
        title={t("fields.filterLeft")}
        description={t("fields.filterLeftHelp")}
      >
        <InputTypeIn
          value={node.left}
          placeholder={t("placeholder.filterLeft")}
          onChange={(event) => onChange({ ...node, left: event.target.value })}
        />
      </InputVertical>

      <InputVertical withLabel title={t("fields.operator")}>
        <InputSingleSelect
          value={node.operator}
          onValueChange={(raw) => {
            const operator = asOperator(raw);
            onChange({
              ...node,
              operator,
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
        <InputVertical withLabel title={t("fields.filterRight")}>
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

/** Keep the wait inside what the server will accept. */
function clampDelay(raw: string): number {
  const parsed = Number.parseFloat(raw);
  if (Number.isNaN(parsed)) return 0;
  return Math.min(MAX_DELAY_SECONDS, Math.max(0, parsed));
}

function RetryFields({ node, onChange }: FieldProps<RetryNode>) {
  const t = useTranslations("flows.inspector");
  const needsValue = !UNARY_OPERATORS.includes(node.operator);

  return (
    <>
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

      <InputVertical
        withLabel
        title={t("fields.untilPath")}
        description={t("fields.untilPathHelp")}
        suffix="optional"
      >
        <InputTypeIn
          value={node.until_path ?? ""}
          placeholder={t("placeholder.untilPath")}
          onChange={(event) =>
            onChange({
              ...node,
              until_path: event.target.value === "" ? null : event.target.value,
            })
          }
        />
      </InputVertical>

      <InputVertical withLabel title={t("fields.operator")}>
        <InputSingleSelect
          value={node.operator}
          onValueChange={(raw) => {
            const operator = asOperator(raw);
            onChange({
              ...node,
              operator,
              value: UNARY_OPERATORS.includes(operator)
                ? null
                : (node.value ?? ""),
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

      {needsValue ? (
        <InputVertical withLabel title={t("fields.untilValue")}>
          <InputTypeIn
            value={node.value ?? ""}
            onChange={(event) =>
              onChange({ ...node, value: event.target.value })
            }
          />
        </InputVertical>
      ) : null}

      <InputVertical
        withLabel
        title={t("fields.maxChecks")}
        description={t("fields.maxChecksHelp")}
      >
        <InputTypeIn
          type="number"
          min={1}
          max={60}
          value={String(node.max_checks)}
          onChange={(event) =>
            onChange({ ...node, max_checks: clampChecks(event.target.value) })
          }
        />
      </InputVertical>

      <InputVertical
        withLabel
        title={t("fields.interval")}
        description={t("fields.intervalHelp")}
      >
        <InputTypeIn
          type="number"
          min={0}
          max={60}
          value={String(node.interval_seconds)}
          onChange={(event) =>
            onChange({
              ...node,
              interval_seconds: clampInterval(event.target.value),
            })
          }
        />
      </InputVertical>

      <Text font="main-ui-muted" color="text-03">
        {t("fields.retryWindow", {
          seconds: Math.round(node.max_checks * node.interval_seconds),
        })}
      </Text>
    </>
  );
}

function WebhookFields({
  node,
  signingSecret,
  onChange,
}: FieldProps<WebhookNode> & { signingSecret: string | null }) {
  const t = useTranslations("flows.inspector");

  return (
    <>
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

      <InputVertical
        withLabel
        title={t("fields.payload")}
        description={t("fields.payloadHelp")}
      >
        <InputTextArea
          value={stringifyPayload(node.payload)}
          rows={6}
          spellCheck={false}
          placeholder={t("placeholder.payload")}
          onChange={(event) =>
            onChange({ ...node, payload: parsePayload(event.target.value) })
          }
        />
      </InputVertical>

      <InputVertical withLabel title={t("fields.headers")} suffix="optional">
        <InputKeyValue
          items={toPairs(node.headers)}
          onChange={(items) => onChange({ ...node, headers: toRecord(items) })}
        />
      </InputVertical>

      {signingSecret !== null ? (
        <InputVertical
          withLabel
          title={t("fields.signingSecret")}
          description={t("fields.signingSecretHelp")}
        >
          <InputTypeIn
            variant="readOnly"
            value={signingSecret}
            data-testid="webhook-signing-secret"
          />
        </InputVertical>
      ) : null}
    </>
  );
}

/**
 * The payload as text the author can edit.
 *
 * A webhook body is arbitrary JSON, so it is a text field rather than a set
 * of key/value rows — nested blocks are exactly what a Slack or Discord
 * delivery needs, and a flat map cannot express them.
 */
function stringifyPayload(payload: JsonValue): string {
  if (payload === null) return "";
  return JSON.stringify(payload, null, 2);
}

/**
 * Text back into a payload, keeping what was typed when it is not valid JSON
 * yet.
 *
 * Half-typed JSON is the normal state of a field somebody is editing. Storing
 * it as a string keeps the keystroke rather than throwing it away, and the
 * server rejects a spec it cannot use.
 */
function parsePayload(raw: string): JsonValue {
  if (raw.trim() === "") return null;
  try {
    return JSON.parse(raw) as JsonValue;
  } catch {
    return raw;
  }
}

/** Keep the check count inside what the server will accept. */
function clampChecks(raw: string): number {
  const parsed = Number.parseInt(raw, 10);
  if (Number.isNaN(parsed)) return 1;
  return Math.min(60, Math.max(1, parsed));
}

/** Keep the wait between checks inside what the server will accept. */
function clampInterval(raw: string): number {
  const parsed = Number.parseFloat(raw);
  if (Number.isNaN(parsed)) return 0;
  return Math.min(60, Math.max(0, parsed));
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
