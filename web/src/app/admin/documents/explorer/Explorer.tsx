"use client";

import { adminSearch } from "./lib";
import { MagnifyingGlass } from "@phosphor-icons/react";
import { useState, useEffect, useCallback } from "react";
import { OnyxDocument } from "@/lib/search/interfaces";
import { buildDocumentSummaryDisplay } from "@/components/search/DocumentDisplay";
import { CustomCheckbox } from "@/components/CustomCheckbox";
import { updateHiddenStatus } from "../lib";
import { PopupSpec, usePopup } from "@/components/admin/connectors/Popup";
import { getErrorMsg } from "@/lib/fetchUtils";
import { ScoreSection } from "../ScoreEditor";
import { useRouter } from "next/navigation";
import { useFilters } from "@/lib/hooks";
import { buildFilters } from "@/lib/search/utils";
import { DocumentUpdatedAtBadge } from "@/components/search/DocumentUpdatedAtBadge";
import { DocumentSetSummary } from "@/lib/types";
import { SourceIcon } from "@/components/SourceIcon";
import { Connector } from "@/lib/connectors/connectors";
import { HorizontalFilters } from "@/components/filters/SourceSelector";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import Text from "@/refresh-components/texts/Text";

const DocumentDisplay = ({
  document,
  refresh,
  setPopup,
}: {
  document: OnyxDocument;
  refresh: () => void;
  setPopup: (popupSpec: PopupSpec | null) => void;
}) => {
  return (
    <div
      key={document.document_id}
      className="text-sm border-b border-border mb-3"
    >
      <div className="flex relative">
        <a
          className={
            "rounded-lg flex font-bold " +
            (document.link ? "" : "pointer-events-none")
          }
          href={document.link}
          target="_blank"
          rel="noopener noreferrer"
        >
          <SourceIcon sourceType={document.source_type} iconSize={22} />
          <p className="truncate break-all ml-2 my-auto text-base">
            {document.semantic_identifier || document.document_id}
          </p>
        </a>
      </div>
      <div className="flex flex-wrap gap-x-2 mt-1 text-xs">
        <div className="px-1 py-0.5 bg-accent-background-hovered rounded flex">
          <p className="mr-1 my-auto">Boost:</p>
          <ScoreSection
            documentId={document.document_id}
            initialScore={document.boost}
            setPopup={setPopup}
            refresh={refresh}
            consistentWidth={false}
          />
        </div>
        <div
          onClick={async () => {
            const response = await updateHiddenStatus(
              document.document_id,
              !document.hidden
            );
            if (response.ok) {
              refresh();
            } else {
              setPopup({
                type: "error",
                message: `Failed to update document - ${getErrorMsg(
                  response
                )}}`,
              });
            }
          }}
          className="px-1 py-0.5 bg-accent-background-hovered hover:bg-accent-background rounded flex cursor-pointer select-none"
        >
          <div className="my-auto">
            {document.hidden ? (
              <div className="text-error">Hidden</div>
            ) : (
              "Visible"
            )}
          </div>
          <div className="ml-1 my-auto">
            <CustomCheckbox checked={!document.hidden} />
          </div>
        </div>
      </div>
      {document.updated_at && (
        <div className="mt-2">
          <DocumentUpdatedAtBadge updatedAt={document.updated_at} />
        </div>
      )}
      <p className="pl-1 pt-2 pb-3 break-words">
        {buildDocumentSummaryDisplay(document.match_highlights, document.blurb)}
      </p>
    </div>
  );
};

export function Explorer({
  initialSearchValue,
  connectors,
  documentSets,
}: {
  initialSearchValue: string | undefined;
  connectors: Connector<any>[];
  documentSets: DocumentSetSummary[];
}) {
  const router = useRouter();
  const { popup, setPopup } = usePopup();

  const [query, setQuery] = useState(initialSearchValue || "");
  const [timeoutId, setTimeoutId] = useState<number | null>(null);
  const [results, setResults] = useState<OnyxDocument[]>([]);

  const filterManager = useFilters();

  const onSearch = useCallback(
    async (query: string) => {
      const filters = buildFilters(
        filterManager.selectedSources,
        filterManager.selectedDocumentSets,
        filterManager.timeRange,
        filterManager.selectedTags
      );
      const results = await adminSearch(query, filters);
      if (results.ok) {
        setResults((await results.json()).documents);
      }
      setTimeoutId(null);
    },
    [
      filterManager.selectedDocumentSets,
      filterManager.selectedSources,
      filterManager.timeRange,
      filterManager.selectedTags,
    ]
  );

  useEffect(() => {
    if (timeoutId !== null) {
      clearTimeout(timeoutId);
    }

    if (query && query.trim() !== "") {
      router.replace(
        `/admin/documents/explorer?query=${encodeURIComponent(query)}`
      );

      const newTimeoutId = window.setTimeout(() => onSearch(query), 300);
      setTimeoutId(newTimeoutId);
    } else {
      setResults([]);
    }
  }, [
    query,
    filterManager.selectedDocumentSets,
    filterManager.selectedSources,
    filterManager.timeRange,
  ]);

  return (
    <div className="flex flex-col gap-padding-content">
      {popup}
      <div className="flex flex-col justify-center gap-spacing-interline">
        <InputTypeIn
          placeholder="Find documents based on title / content..."
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
          }}
          onKeyDown={(event) => {
            if (
              event.key === "Enter" &&
              !event.shiftKey &&
              !(event.nativeEvent as any).isComposing
            ) {
              onSearch(query);
              event.preventDefault();
            }
          }}
          role="textarea"
        />

        <HorizontalFilters
          {...filterManager}
          availableDocumentSets={documentSets}
          existingSources={connectors.map((connector) => connector.source)}
          availableTags={[]}
          toggleFilters={() => {}}
          filtersUntoggled={false}
          tagsOnLeft={true}
        />
        <div className="border-b" />
      </div>
      {results.length > 0 && (
        <div className="mt-3">
          {results.map((document) => {
            return (
              <DocumentDisplay
                key={document.document_id}
                document={document}
                refresh={() => onSearch(query)}
                setPopup={setPopup}
              />
            );
          })}
        </div>
      )}
      {!query && (
        <Text className="">
          Search for a document above to modify its boost or hide it from
          searches.
        </Text>
      )}
    </div>
  );
}
