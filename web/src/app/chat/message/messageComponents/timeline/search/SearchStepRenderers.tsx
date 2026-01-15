import React, { JSX } from "react";
import { SvgSearch, SvgBookOpen, SvgXCircle } from "@opal/icons";
import { SearchToolPacket } from "@/app/chat/services/streamingModels";
import { RendererResult } from "@/app/chat/message/messageComponents/interfaces";
import { BlinkingDot } from "@/app/chat/message/BlinkingDot";
import { OnyxDocument } from "@/lib/search/interfaces";
import { ResultIcon } from "@/components/chat/sources/SourceCard";
import { SearchChipList } from "./SearchChipList";
import {
  constructCurrentSearchState,
  INITIAL_QUERIES_TO_SHOW,
  QUERIES_PER_EXPANSION,
  INITIAL_RESULTS_TO_SHOW,
  RESULTS_PER_EXPANSION,
} from "./searchStateUtils";

interface StepRendererProps {
  packets: SearchToolPacket[];
  isActive: boolean;
  isCancelled?: boolean;
  children: (result: RendererResult) => JSX.Element;
}

/**
 * Step 1 Renderer: Shows "Searching internally" with search queries.
 * Used by MultiToolRenderer for the first step of internal search.
 */
export function SourceRetrievalStepRenderer({
  packets,
  isActive,
  isCancelled,
  children,
}: StepRendererProps): JSX.Element {
  const state = constructCurrentSearchState(packets);

  return children({
    icon: SvgSearch,
    status: "Searching internally",
    content: (
      <div className="flex flex-col">
        <SearchChipList
          items={state.queries}
          initialCount={INITIAL_QUERIES_TO_SHOW}
          expansionCount={QUERIES_PER_EXPANSION}
          getKey={(_, index) => index}
          getIcon={() => <SvgSearch size={10} />}
          getTitle={(query: string) => query}
          emptyState={
            isCancelled ? (
              <SvgXCircle size={14} className="text-text-400" />
            ) : (
              <BlinkingDot />
            )
          }
        />
      </div>
    ),
  });
}

/**
 * Step 2 Renderer: Shows "Reading" with retrieved documents.
 * Used by MultiToolRenderer for the second step of internal search.
 */
export function ReadDocumentsStepRenderer({
  packets,
  isActive,
  isCancelled,
  children,
}: StepRendererProps): JSX.Element {
  const state = constructCurrentSearchState(packets);

  return children({
    icon: SvgBookOpen,
    status: "Reading",
    content: (
      <div className="flex flex-col">
        <SearchChipList
          items={state.results}
          initialCount={INITIAL_RESULTS_TO_SHOW}
          expansionCount={RESULTS_PER_EXPANSION}
          getKey={(doc: OnyxDocument) => doc.document_id}
          getIcon={(doc: OnyxDocument) => <ResultIcon doc={doc} size={10} />}
          getTitle={(doc: OnyxDocument) => doc.semantic_identifier || ""}
          onClick={(doc: OnyxDocument) => {
            if (doc.link) {
              window.open(doc.link, "_blank");
            }
          }}
          emptyState={
            isCancelled ? (
              <SvgXCircle size={14} className="text-text-400" />
            ) : (
              <BlinkingDot />
            )
          }
        />
      </div>
    ),
  });
}
