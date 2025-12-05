"use client";

import { useEffect, useMemo, useState } from "react";
import {
  FiUsers,
  FiChevronDown,
  FiChevronRight,
  FiSearch,
  FiBookOpen,
  FiCheck,
} from "react-icons/fi";
import { RenderType, MessageRenderer } from "../interfaces";
import { Packet, PacketType } from "@/app/chat/services/streamingModels";
import { OnyxDocument } from "@/lib/search/interfaces";
import { SourceChip2 } from "@/app/chat/components/SourceChip2";
import { truncateString } from "@/lib/utils";
import { ResultIcon } from "@/components/chat/sources/SourceCard";
import { BlinkingDot } from "../../BlinkingDot";

const MAX_TITLE_LENGTH = 25;
const INITIAL_QUERIES_TO_SHOW = 3;
const QUERIES_PER_EXPANSION = 5;
const INITIAL_RESULTS_TO_SHOW = 3;
const RESULTS_PER_EXPANSION = 10;

interface AgentRunState {
  agentName: string;
  agentId: number;
  statusText: string;
  nestedContent: string;
  summary: string;
  fullResponse: string;
  isRunning: boolean;
  isComplete: boolean;
  nestedSearchQueries: string[];
  nestedSearchDocs: OnyxDocument[];
  hasNestedSearch: boolean;
  depth: number;
}

function buildAgentRunsFromPackets(packets: Packet[]): AgentRunState[] {
  const runs: AgentRunState[] = [];
  const stack: AgentRunState[] = [];

  for (const packet of packets) {
    const obj = packet.obj;

    if (obj.type === PacketType.AGENT_TOOL_START) {
      const run: AgentRunState = {
        agentName: obj.agent_name || "",
        agentId: obj.agent_id || 0,
        statusText: "",
        nestedContent: "",
        summary: "",
        fullResponse: "",
        isRunning: true,
        isComplete: false,
        nestedSearchQueries: [],
        nestedSearchDocs: [],
        hasNestedSearch: false,
        depth: stack.length,
      };
      runs.push(run);
      stack.push(run);
    } else if (obj.type === PacketType.AGENT_TOOL_DELTA) {
      const run = stack[stack.length - 1];
      if (!run) continue;
      if (obj.status_text) {
        run.statusText = obj.status_text;
      }
      if (obj.nested_content) {
        run.nestedContent += obj.nested_content;
      }
    } else if (obj.type === PacketType.AGENT_TOOL_FINAL) {
      const run = stack[stack.length - 1];
      if (!run) continue;
      run.summary = obj.summary || "";
      run.fullResponse = obj.full_response || "";
      run.isRunning = false;
      run.isComplete = true;
      stack.pop();
    } else if (
      obj.type === PacketType.SEARCH_TOOL_START ||
      obj.type === PacketType.SEARCH_TOOL_QUERIES_DELTA ||
      obj.type === PacketType.SEARCH_TOOL_DOCUMENTS_DELTA
    ) {
      const run = stack[stack.length - 1];
      if (!run) continue;
      if (obj.type === PacketType.SEARCH_TOOL_START) {
        run.hasNestedSearch = true;
      } else if (obj.type === PacketType.SEARCH_TOOL_QUERIES_DELTA) {
        run.nestedSearchQueries = obj.queries || [];
      } else if (obj.type === PacketType.SEARCH_TOOL_DOCUMENTS_DELTA) {
        run.nestedSearchDocs = obj.documents || [];
      }
    }
  }

  return runs;
}

function AgentRunRenderer({
  run,
  renderType,
  depth,
  onComplete,
  children,
}: {
  run: AgentRunState;
  renderType: RenderType;
  depth: number;
  onComplete: () => void;
  children: any;
}) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [queriesToShow, setQueriesToShow] = useState(INITIAL_QUERIES_TO_SHOW);
  const [resultsToShow, setResultsToShow] = useState(INITIAL_RESULTS_TO_SHOW);

  useEffect(() => {
    if (run.isComplete) {
      onComplete();
    }
  }, [run.isComplete, onComplete]);

  const status = useMemo(() => {
    if (run.isComplete) {
      return `Agent: ${run.agentName}`;
    }
    if (run.isRunning) {
      return `Agent: ${run.agentName}`;
    }
    return null;
  }, [run.agentName, run.isComplete, run.isRunning]);

  const icon = FiUsers;

  if (renderType === RenderType.HIGHLIGHT) {
    return children({
      icon,
      status: status,
      content: (
        <div
          className="flex flex-col gap-1 text-sm text-muted-foreground"
          style={{ marginLeft: depth ? depth * 12 : 0 }}
        >
          <div className="flex items-center gap-2">
            <span className="font-medium text-foreground">
              Agent: {run.agentName}
            </span>
            {run.isRunning && (
              <span className="text-xs text-blue-500">working…</span>
            )}
            {run.isComplete && (
              <span className="text-xs text-green-600 dark:text-green-400 flex items-center gap-1">
                <FiCheck className="w-3 h-3" />
                completed
              </span>
            )}
          </div>
          {run.statusText && (
            <div className="text-xs text-muted-foreground">
              {run.statusText}
            </div>
          )}
        </div>
      ),
    });
  }

  return children({
    icon,
    status,
    content: (
      <div
        className="flex flex-col mt-1.5"
        style={{ marginLeft: depth ? depth * 14 : 0 }}
      >
        {run.hasNestedSearch && (
          <div className="flex flex-col mt-3">
            <div className="flex items-center gap-2 mb-2 ml-1">
              <FiSearch className="w-3.5 h-3.5 text-gray-500" />
              <span className="text-sm text-gray-600 dark:text-gray-400">
                Searching internally
              </span>
              {run.nestedSearchQueries.length > 0 && (
                <span className="text-xs text-gray-500">
                  ({run.nestedSearchQueries.length} queries)
                </span>
              )}
            </div>
            <div className="flex flex-wrap gap-x-2 gap-y-2 ml-1">
              {run.nestedSearchQueries
                .slice(0, queriesToShow)
                .map((query, index) => (
                  <div
                    key={index}
                    className="text-xs animate-in fade-in slide-in-from-left-2 duration-150"
                    style={{
                      animationDelay: `${index * 30}ms`,
                      animationFillMode: "backwards",
                    }}
                  >
                    <SourceChip2
                      icon={<FiSearch size={10} />}
                      title={truncateString(query, MAX_TITLE_LENGTH)}
                    />
                  </div>
                ))}
              {run.nestedSearchQueries.length > queriesToShow && (
                <div
                  className="text-xs animate-in fade-in slide-in-from-left-2 duration-150"
                  style={{
                    animationDelay: `${queriesToShow * 30}ms`,
                    animationFillMode: "backwards",
                  }}
                >
                  <SourceChip2
                    title={`${
                      run.nestedSearchQueries.length - queriesToShow
                    } more...`}
                    onClick={() => {
                      setQueriesToShow((prev) =>
                        Math.min(
                          prev + QUERIES_PER_EXPANSION,
                          run.nestedSearchQueries.length
                        )
                      );
                    }}
                  />
                </div>
              )}
              {run.nestedSearchQueries.length === 0 && run.isRunning && (
                <BlinkingDot />
              )}
            </div>
          </div>
        )}

        {run.nestedSearchDocs.length > 0 && (
          <div className="flex flex-col mt-3">
            <div className="flex items-center gap-2 mb-2 ml-1">
              <FiBookOpen className="w-3.5 h-3.5 text-gray-500" />
              <span className="text-sm text-gray-600 dark:text-gray-400">
                Reading documents
              </span>
            </div>
            <div className="flex flex-wrap gap-x-2 gap-y-2 ml-1">
              {run.nestedSearchDocs
                .slice(0, resultsToShow)
                .map((doc, index) => (
                  <div
                    key={doc.document_id}
                    className="text-xs animate-in fade-in slide-in-from-left-2 duration-150"
                    style={{
                      animationDelay: `${index * 30}ms`,
                      animationFillMode: "backwards",
                    }}
                  >
                    <SourceChip2
                      icon={<ResultIcon doc={doc} size={10} />}
                      title={truncateString(
                        doc.semantic_identifier || "",
                        MAX_TITLE_LENGTH
                      )}
                      onClick={() => {
                        if (doc.link) {
                          window.open(doc.link, "_blank");
                        }
                      }}
                    />
                  </div>
                ))}
              {run.nestedSearchDocs.length > resultsToShow && (
                <div
                  className="text-xs animate-in fade-in slide-in-from-left-2 duration-150"
                  style={{
                    animationDelay: `${
                      Math.min(resultsToShow, run.nestedSearchDocs.length) * 30
                    }ms`,
                    animationFillMode: "backwards",
                  }}
                >
                  <SourceChip2
                    title={`${
                      run.nestedSearchDocs.length - resultsToShow
                    } more...`}
                    onClick={() => {
                      setResultsToShow((prev) =>
                        Math.min(
                          prev + RESULTS_PER_EXPANSION,
                          run.nestedSearchDocs.length
                        )
                      );
                    }}
                  />
                </div>
              )}
              {run.nestedSearchDocs.length === 0 &&
                run.nestedSearchQueries.length > 0 &&
                run.isRunning && <BlinkingDot />}
            </div>
          </div>
        )}

        {run.isRunning && run.nestedContent && (
          <div className="mt-3 text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap border-l-2 border-blue-200 dark:border-blue-800 pl-3 ml-1">
            {run.nestedContent}
          </div>
        )}

        {run.isComplete && run.fullResponse && (
          <div className="mt-3 ml-1">
            <button
              type="button"
              onClick={() => setIsExpanded(!isExpanded)}
              className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
            >
              {isExpanded ? (
                <FiChevronDown className="w-3 h-3" />
              ) : (
                <FiChevronRight className="w-3 h-3" />
              )}
              {isExpanded ? "Hide agent response" : "View agent response"}
            </button>
            {isExpanded && (
              <div className="mt-2 text-sm bg-gray-50 dark:bg-gray-800 p-3 rounded border max-h-96 overflow-y-auto whitespace-pre-wrap">
                {run.fullResponse}
              </div>
            )}
          </div>
        )}

        {run.isRunning && !run.nestedContent && !run.hasNestedSearch && (
          <div className="ml-1">
            <BlinkingDot />
          </div>
        )}
      </div>
    ),
  });
}

export const AgentToolRenderer: MessageRenderer<Packet, {}> = ({
  packets,
  onComplete,
  renderType,
  children,
}) => {
  const runs = buildAgentRunsFromPackets(packets);

  return (
    <>
      {runs.map((run, idx) => (
        <AgentRunRenderer
          key={`${run.agentName}-${idx}`}
          run={run}
          renderType={renderType}
          depth={run.depth}
          onComplete={onComplete}
        >
          {children}
        </AgentRunRenderer>
      ))}
    </>
  );
};

export default AgentToolRenderer;
