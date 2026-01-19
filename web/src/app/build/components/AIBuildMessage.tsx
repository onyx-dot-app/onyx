"use client";

import React, { useRef, useState, useCallback, useMemo } from "react";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import Logo from "@/refresh-components/Logo";
import MinimalMarkdown from "@/components/chat/MinimalMarkdown";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/refresh-components/Collapsible";
import {
  SvgChevronDown,
  SvgChevronRight,
  SvgTerminalSmall,
  SvgCheckCircle,
  SvgLoader,
  SvgAlertCircle,
  SvgFileText,
  SvgCode,
  SvgEdit,
  SvgGlobe,
  SvgTrash,
  SvgFiles,
  SvgImage,
  SvgBarChart,
} from "@opal/icons";

// ============================================
// Streaming Protocol Types (from cc4a-overview.md)
// ============================================

export enum StreamingType {
  // Control packets
  DONE = "done",
  ERROR = "error",

  // Agent activity packets
  STEP_START = "step_start",
  STEP_DELTA = "step_delta",
  STEP_END = "step_end",

  // Output packets (final response)
  OUTPUT_START = "output_start",
  OUTPUT_DELTA = "output_delta",

  // Artifact packets
  ARTIFACT_CREATED = "artifact_created",
  ARTIFACT_UPDATED = "artifact_updated",

  // Tool usage packets
  TOOL_START = "tool_start",
  TOOL_OUTPUT = "tool_output",
  TOOL_END = "tool_end",

  // File operation packets
  FILE_WRITE = "file_write",
  FILE_DELETE = "file_delete",
}

export type ArtifactType =
  | "nextjs_app"
  | "pptx"
  | "markdown"
  | "chart"
  | "csv"
  | "image";

export interface ArtifactMetadata {
  id: string;
  type: ArtifactType;
  name: string;
  path: string;
  preview_url?: string;
}

// Base packet interface
interface BasePacket {
  type: string;
  timestamp: string;
}

// Control packets
export interface DonePacket extends BasePacket {
  type: "done";
  summary?: string;
}

export interface ErrorPacket extends BasePacket {
  type: "error";
  message: string;
  code?: string;
  recoverable: boolean;
}

// Step packets
export interface StepStart extends BasePacket {
  type: "step_start";
  step_id: string;
  title?: string;
}

export interface StepDelta extends BasePacket {
  type: "step_delta";
  step_id: string;
  content: string;
}

export interface StepEnd extends BasePacket {
  type: "step_end";
  step_id: string;
  status: "success" | "failed" | "skipped";
}

// Output packets
export interface OutputStart extends BasePacket {
  type: "output_start";
}

export interface OutputDelta extends BasePacket {
  type: "output_delta";
  content: string;
}

// Artifact packets
export interface ArtifactCreated extends BasePacket {
  type: "artifact_created";
  artifact: ArtifactMetadata;
}

export interface ArtifactUpdated extends BasePacket {
  type: "artifact_updated";
  artifact: ArtifactMetadata;
  changes?: string[];
}

// Tool packets
export interface ToolStart extends BasePacket {
  type: "tool_start";
  tool_name: string;
  tool_input?: Record<string, unknown> | string;
}

export interface ToolOutput extends BasePacket {
  type: "tool_output";
  tool_name: string;
  output?: string;
  is_error: boolean;
}

export interface ToolEnd extends BasePacket {
  type: "tool_end";
  tool_name: string;
  status: "success" | "failed";
}

// File packets
export interface FileWrite extends BasePacket {
  type: "file_write";
  path: string;
  size_bytes?: number;
}

export interface FileDelete extends BasePacket {
  type: "file_delete";
  path: string;
}

// Discriminated union of all packet types
export type BuildStreamPacket =
  | DonePacket
  | ErrorPacket
  | StepStart
  | StepDelta
  | StepEnd
  | OutputStart
  | OutputDelta
  | ArtifactCreated
  | ArtifactUpdated
  | ToolStart
  | ToolOutput
  | ToolEnd
  | FileWrite
  | FileDelete;

// ============================================
// Parsed State Types
// ============================================

interface ParsedStep {
  id: string;
  title?: string;
  content: string;
  status: "in_progress" | "success" | "failed" | "skipped";
}

interface ParsedTool {
  name: string;
  input?: Record<string, unknown> | string;
  output?: string;
  status: "in_progress" | "success" | "failed";
  isError: boolean;
}

interface ParsedArtifact {
  id: string;
  type: ArtifactType;
  name: string;
  path: string;
  previewUrl?: string;
  isNew: boolean;
  changes?: string[];
}

interface ParsedFileOp {
  path: string;
  operation: "write" | "delete";
  sizeBytes?: number;
}

interface ParsedState {
  steps: Map<string, ParsedStep>;
  tools: ParsedTool[];
  artifacts: Map<string, ParsedArtifact>;
  fileOps: ParsedFileOp[];
  outputContent: string;
  isOutputStarted: boolean;
  isDone: boolean;
  doneSummary?: string;
  error?: { message: string; code?: string; recoverable: boolean };
}

// ============================================
// Helper Functions
// ============================================

function getToolIcon(toolName: string) {
  const name = toolName.toLowerCase();
  if (name.includes("bash") || name.includes("terminal")) {
    return SvgTerminalSmall;
  }
  if (name.includes("read")) {
    return SvgFileText;
  }
  if (name.includes("write") || name.includes("edit")) {
    return SvgEdit;
  }
  if (
    name.includes("web") ||
    name.includes("fetch") ||
    name.includes("search")
  ) {
    return SvgGlobe;
  }
  return SvgCode;
}

function getArtifactIcon(type: ArtifactType) {
  switch (type) {
    case "nextjs_app":
      return SvgCode;
    case "pptx":
      return SvgBarChart;
    case "markdown":
      return SvgFileText;
    case "chart":
      return SvgBarChart;
    case "csv":
      return SvgFiles;
    case "image":
      return SvgImage;
    default:
      return SvgFiles;
  }
}

function getArtifactLabel(type: ArtifactType): string {
  switch (type) {
    case "nextjs_app":
      return "Web App";
    case "pptx":
      return "Presentation";
    case "markdown":
      return "Document";
    case "chart":
      return "Chart";
    case "csv":
      return "CSV Data";
    case "image":
      return "Image";
    default:
      return "Artifact";
  }
}

// ============================================
// Packet Parsing
// ============================================

function parsePackets(packets: BuildStreamPacket[]): ParsedState {
  const state: ParsedState = {
    steps: new Map(),
    tools: [],
    artifacts: new Map(),
    fileOps: [],
    outputContent: "",
    isOutputStarted: false,
    isDone: false,
  };

  // Track active tools by name for matching start/output/end
  const activeToolIndex = new Map<string, number>();

  for (const packet of packets) {
    switch (packet.type) {
      case StreamingType.STEP_START: {
        const p = packet as StepStart;
        state.steps.set(p.step_id, {
          id: p.step_id,
          title: p.title,
          content: "",
          status: "in_progress",
        });
        break;
      }

      case StreamingType.STEP_DELTA: {
        const p = packet as StepDelta;
        const step = state.steps.get(p.step_id);
        if (step) {
          step.content += p.content;
        }
        break;
      }

      case StreamingType.STEP_END: {
        const p = packet as StepEnd;
        const step = state.steps.get(p.step_id);
        if (step) {
          step.status = p.status;
        }
        break;
      }

      case StreamingType.OUTPUT_START: {
        state.isOutputStarted = true;
        break;
      }

      case StreamingType.OUTPUT_DELTA: {
        const p = packet as OutputDelta;
        state.outputContent += p.content;
        break;
      }

      case StreamingType.TOOL_START: {
        const p = packet as ToolStart;
        const toolIndex = state.tools.length;
        state.tools.push({
          name: p.tool_name,
          input: p.tool_input,
          status: "in_progress",
          isError: false,
        });
        activeToolIndex.set(p.tool_name, toolIndex);
        break;
      }

      case StreamingType.TOOL_OUTPUT: {
        const p = packet as ToolOutput;
        const idx = activeToolIndex.get(p.tool_name);
        if (idx !== undefined && state.tools[idx]) {
          state.tools[idx].output = p.output;
          state.tools[idx].isError = p.is_error;
        }
        break;
      }

      case StreamingType.TOOL_END: {
        const p = packet as ToolEnd;
        const idx = activeToolIndex.get(p.tool_name);
        if (idx !== undefined && state.tools[idx]) {
          state.tools[idx].status = p.status;
        }
        activeToolIndex.delete(p.tool_name);
        break;
      }

      case StreamingType.ARTIFACT_CREATED: {
        const p = packet as ArtifactCreated;
        state.artifacts.set(p.artifact.id, {
          id: p.artifact.id,
          type: p.artifact.type,
          name: p.artifact.name,
          path: p.artifact.path,
          previewUrl: p.artifact.preview_url,
          isNew: true,
        });
        break;
      }

      case StreamingType.ARTIFACT_UPDATED: {
        const p = packet as ArtifactUpdated;
        const existing = state.artifacts.get(p.artifact.id);
        state.artifacts.set(p.artifact.id, {
          id: p.artifact.id,
          type: p.artifact.type,
          name: p.artifact.name,
          path: p.artifact.path,
          previewUrl: p.artifact.preview_url,
          isNew: existing ? false : true,
          changes: p.changes,
        });
        break;
      }

      case StreamingType.FILE_WRITE: {
        const p = packet as FileWrite;
        state.fileOps.push({
          path: p.path,
          operation: "write",
          sizeBytes: p.size_bytes,
        });
        break;
      }

      case StreamingType.FILE_DELETE: {
        const p = packet as FileDelete;
        state.fileOps.push({
          path: p.path,
          operation: "delete",
        });
        break;
      }

      case StreamingType.DONE: {
        const p = packet as DonePacket;
        state.isDone = true;
        state.doneSummary = p.summary;
        break;
      }

      case StreamingType.ERROR: {
        const p = packet as ErrorPacket;
        state.error = {
          message: p.message,
          code: p.code,
          recoverable: p.recoverable,
        };
        break;
      }
    }
  }

  return state;
}

// ============================================
// Sub-components
// ============================================

interface StepBubbleProps {
  step: ParsedStep;
}

function StepBubble({ step }: StepBubbleProps) {
  const [isOpen, setIsOpen] = useState(false);
  const isComplete = step.status !== "in_progress";
  const isFailed = step.status === "failed";

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <CollapsibleTrigger asChild>
        <button
          className={cn(
            "inline-flex flex-row items-center gap-1.5 px-2.5 py-1.5 rounded-full",
            "border transition-all text-left",
            isFailed
              ? "bg-status-error-01 border-status-error-02"
              : isComplete
                ? "bg-background-neutral-01 border-border-02 hover:bg-background-neutral-02"
                : "bg-status-info-01 border-status-info-02"
          )}
        >
          {!isComplete ? (
            <SvgLoader className="size-3.5 stroke-status-info-05 animate-spin shrink-0" />
          ) : isFailed ? (
            <SvgAlertCircle className="size-3.5 stroke-status-error-05 shrink-0" />
          ) : (
            <SvgCheckCircle className="size-3.5 stroke-status-success-05 shrink-0" />
          )}
          <span className="text-xs font-medium text-text-04">
            {step.title || "Step"}
          </span>
          {step.content && (
            <>
              {isOpen ? (
                <SvgChevronDown className="size-3 stroke-text-03 shrink-0" />
              ) : (
                <SvgChevronRight className="size-3 stroke-text-03 shrink-0" />
              )}
            </>
          )}
        </button>
      </CollapsibleTrigger>
      {step.content && (
        <CollapsibleContent>
          <div
            className={cn(
              "mt-2 p-3 rounded-08 border border-border-01",
              "bg-background-neutral-02 text-text-05",
              "text-xs overflow-x-auto max-h-48 overflow-y-auto"
            )}
          >
            <MinimalMarkdown content={step.content} />
          </div>
        </CollapsibleContent>
      )}
    </Collapsible>
  );
}

interface ToolBubbleProps {
  tool: ParsedTool;
}

function ToolBubble({ tool }: ToolBubbleProps) {
  const [isOpen, setIsOpen] = useState(false);
  const isComplete = tool.status !== "in_progress";
  const isFailed = tool.status === "failed" || tool.isError;
  const Icon = getToolIcon(tool.name);

  const inputStr = useMemo(() => {
    if (!tool.input) return "";
    if (typeof tool.input === "string") return tool.input;
    return JSON.stringify(tool.input, null, 2);
  }, [tool.input]);

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <CollapsibleTrigger asChild>
        <button
          className={cn(
            "inline-flex flex-row items-center gap-1.5 px-2.5 py-1.5 rounded-full",
            "border transition-all text-left",
            isFailed
              ? "bg-status-error-01 border-status-error-02"
              : isComplete
                ? "bg-background-neutral-01 border-border-02 hover:bg-background-neutral-02"
                : "bg-status-info-01 border-status-info-02"
          )}
        >
          {!isComplete ? (
            <SvgLoader className="size-3.5 stroke-status-info-05 animate-spin shrink-0" />
          ) : (
            <Icon className="size-3.5 stroke-text-03 shrink-0" />
          )}
          <span className="text-xs font-medium text-text-04">{tool.name}</span>
          {isComplete && !isFailed && (
            <SvgCheckCircle className="size-3.5 stroke-status-success-05 shrink-0 ml-0.5" />
          )}
          {isFailed && (
            <SvgAlertCircle className="size-3.5 stroke-status-error-05 shrink-0 ml-0.5" />
          )}
          {isOpen ? (
            <SvgChevronDown className="size-3 stroke-text-03 shrink-0" />
          ) : (
            <SvgChevronRight className="size-3 stroke-text-03 shrink-0" />
          )}
        </button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div
          className={cn(
            "mt-2 p-3 rounded-08 border border-border-01",
            "bg-background-neutral-inverted-03 text-text-inverted-05",
            "text-xs overflow-x-auto max-h-48 overflow-y-auto"
          )}
          style={{ fontFamily: "var(--font-dm-mono)" }}
        >
          {inputStr && (
            <div className="mb-2">
              <span className="text-text-inverted-03">Input:</span>
              <pre className="whitespace-pre-wrap break-words m-0 mt-1">
                {inputStr}
              </pre>
            </div>
          )}
          {tool.output && (
            <div>
              <span className="text-text-inverted-03">Output:</span>
              <pre className="whitespace-pre-wrap break-words m-0 mt-1">
                {tool.output}
              </pre>
            </div>
          )}
          {!inputStr && !tool.output && (
            <span className="text-text-inverted-03">Waiting for output...</span>
          )}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

interface ArtifactBubbleProps {
  artifact: ParsedArtifact;
  onClick?: (artifact: ParsedArtifact) => void;
}

function ArtifactBubble({ artifact, onClick }: ArtifactBubbleProps) {
  const Icon = getArtifactIcon(artifact.type);
  const label = getArtifactLabel(artifact.type);

  return (
    <button
      onClick={() => onClick?.(artifact)}
      className={cn(
        "inline-flex flex-row items-center gap-2 px-3 py-2 rounded-08",
        "border border-border-02 bg-background-neutral-01",
        "hover:bg-background-neutral-02 transition-all text-left",
        "shadow-sm"
      )}
    >
      <Icon className="size-5 stroke-text-03 shrink-0" />
      <div className="flex flex-col min-w-0">
        <span className="text-sm font-medium text-text-05 truncate">
          {artifact.name}
        </span>
        <span className="text-xs text-text-03">
          {label}
          {artifact.isNew && (
            <span className="ml-1 text-status-success-05">• New</span>
          )}
          {artifact.changes && artifact.changes.length > 0 && (
            <span className="ml-1 text-status-info-05">• Updated</span>
          )}
        </span>
      </div>
      <SvgChevronRight className="size-4 stroke-text-03 shrink-0 ml-auto" />
    </button>
  );
}

interface FileOpItemProps {
  fileOp: ParsedFileOp;
}

function FileOpItem({ fileOp }: FileOpItemProps) {
  const isDelete = fileOp.operation === "delete";

  return (
    <div
      className={cn(
        "inline-flex flex-row items-center gap-1.5 px-2 py-1 rounded",
        "text-xs",
        isDelete ? "text-status-error-04" : "text-text-03"
      )}
    >
      {isDelete ? (
        <SvgTrash className="size-3 shrink-0" />
      ) : (
        <SvgEdit className="size-3 shrink-0" />
      )}
      <span className="truncate max-w-[200px]" title={fileOp.path}>
        {fileOp.path}
      </span>
      {fileOp.sizeBytes !== undefined && (
        <span className="text-text-02">
          ({(fileOp.sizeBytes / 1024).toFixed(1)}KB)
        </span>
      )}
    </div>
  );
}

// ============================================
// Main Component
// ============================================

export interface AIBuildMessageProps {
  rawPackets: BuildStreamPacket[];
  isStreaming?: boolean;
  onArtifactClick?: (artifact: ParsedArtifact) => void;
}

function arePropsEqual(
  prev: AIBuildMessageProps,
  next: AIBuildMessageProps
): boolean {
  return (
    prev.rawPackets.length === next.rawPackets.length &&
    prev.isStreaming === next.isStreaming &&
    prev.onArtifactClick === next.onArtifactClick
  );
}

const AIBuildMessage = React.memo(function AIBuildMessage({
  rawPackets,
  isStreaming = false,
  onArtifactClick,
}: AIBuildMessageProps) {
  // Parse packets incrementally
  const lastProcessedIndexRef = useRef<number>(0);
  const parsedStateRef = useRef<ParsedState>({
    steps: new Map(),
    tools: [],
    artifacts: new Map(),
    fileOps: [],
    outputContent: "",
    isOutputStarted: false,
    isDone: false,
  });

  // Reset if packets array was replaced with shorter one
  if (lastProcessedIndexRef.current > rawPackets.length) {
    lastProcessedIndexRef.current = 0;
    parsedStateRef.current = {
      steps: new Map(),
      tools: [],
      artifacts: new Map(),
      fileOps: [],
      outputContent: "",
      isOutputStarted: false,
      isDone: false,
    };
  }

  // Process new packets
  if (rawPackets.length > lastProcessedIndexRef.current) {
    // Re-parse all packets for simplicity (could optimize for incremental)
    parsedStateRef.current = parsePackets(rawPackets);
    lastProcessedIndexRef.current = rawPackets.length;
  }

  const state = parsedStateRef.current;
  const steps = Array.from(state.steps.values());
  const artifacts = Array.from(state.artifacts.values());

  // Determine if we should show the output section
  const showOutput = state.isOutputStarted && state.outputContent.length > 0;
  const showSteps = steps.length > 0;
  const showTools = state.tools.length > 0;
  const showArtifacts = artifacts.length > 0;
  const showFileOps = state.fileOps.length > 0;
  const showError = !!state.error;

  const hasContent =
    showOutput ||
    showSteps ||
    showTools ||
    showArtifacts ||
    showFileOps ||
    showError;

  // Handle artifact click
  const handleArtifactClick = useCallback(
    (artifact: ParsedArtifact) => {
      onArtifactClick?.(artifact);
    },
    [onArtifactClick]
  );

  return (
    <div
      className="flex items-start gap-3 py-4"
      data-testid={state.isDone ? "build-ai-message" : undefined}
    >
      <div className="shrink-0 mt-0.5">
        <Logo folded size={24} />
      </div>
      <div className="flex-1 flex flex-col gap-3 min-w-0">
        {!hasContent && isStreaming ? (
          <div className="flex items-center gap-2 py-1">
            <SvgLoader className="size-4 stroke-text-03 animate-spin" />
            <Text secondaryBody text03>
              Thinking...
            </Text>
          </div>
        ) : (
          <>
            {/* Error display */}
            {showError && state.error && (
              <div
                className={cn(
                  "flex flex-row items-start gap-2 px-3 py-2 rounded-08",
                  "bg-status-error-01 border border-status-error-02"
                )}
              >
                <SvgAlertCircle className="size-4 stroke-status-error-05 shrink-0 mt-0.5" />
                <div className="flex flex-col gap-1">
                  <Text secondaryBody className="text-status-error-05">
                    {state.error.message}
                  </Text>
                  {state.error.code && (
                    <Text secondaryBody text03>
                      Code: {state.error.code}
                    </Text>
                  )}
                </div>
              </div>
            )}

            {/* Steps section */}
            {showSteps && (
              <div className="flex flex-wrap gap-2">
                {steps.map((step) => (
                  <StepBubble key={step.id} step={step} />
                ))}
              </div>
            )}

            {/* Tools section */}
            {showTools && (
              <div className="flex flex-wrap gap-2">
                {state.tools.map((tool, idx) => (
                  <ToolBubble key={`${tool.name}-${idx}`} tool={tool} />
                ))}
              </div>
            )}

            {/* File operations */}
            {showFileOps && (
              <div className="flex flex-wrap gap-1 px-1">
                {state.fileOps.map((fileOp, idx) => (
                  <FileOpItem key={`${fileOp.path}-${idx}`} fileOp={fileOp} />
                ))}
              </div>
            )}

            {/* Artifacts section */}
            {showArtifacts && (
              <div className="flex flex-col gap-2">
                {artifacts.map((artifact) => (
                  <ArtifactBubble
                    key={artifact.id}
                    artifact={artifact}
                    onClick={handleArtifactClick}
                  />
                ))}
              </div>
            )}

            {/* Output/Response section */}
            {showOutput && (
              <div className="py-1">
                <MinimalMarkdown
                  content={state.outputContent}
                  className="text-text-05"
                />
              </div>
            )}

            {/* Streaming indicator when output started but not done */}
            {state.isOutputStarted && !state.isDone && isStreaming && (
              <div className="flex items-center gap-1">
                <SvgLoader className="size-3 stroke-text-03 animate-spin" />
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}, arePropsEqual);

export default AIBuildMessage;
