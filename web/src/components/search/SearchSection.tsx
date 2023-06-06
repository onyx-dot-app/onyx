"use client";

import { useEffect, useState } from "react";
import { SearchBar } from "./SearchBar";
import { SearchResultsDisplay } from "./SearchResultsDisplay";
import { SourceSelector } from "./Filters";
import { Connector } from "@/lib/types";
import { SearchType, SearchTypeSelector } from "./SearchTypeSelector";
import {
  DanswerDocument,
  Quote,
  SearchResponse,
  Source,
} from "@/lib/search/interfaces";
import { keywordSearch } from "@/lib/search/keyword";
import { aiSearchRequestStreamed } from "@/lib/search/ai";
import Cookies from "js-cookie";

interface SearchSectionProps {
  connectors: Connector<any>[];
  defaultSearchType: SearchType;
}

export const SearchSection: React.FC<SearchSectionProps> = ({
  connectors,
  defaultSearchType,
}) => {
  // Search
  const [searchResponse, setSearchResponse] = useState<SearchResponse | null>(
    null
  );
  const [isFetching, setIsFetching] = useState(false);

  // Filters
  const [sources, setSources] = useState<Source[]>([]);

  // Search Type
  const [selectedSearchType, setSelectedSearchType] =
    useState<SearchType>(defaultSearchType);

  // if the user updates value, store into localStorage so it persists across sessions
  useEffect(() => {
    Cookies.set("searchType", selectedSearchType);
    // localStorage.setItem("searchType", selectedSearchType);
  }, [selectedSearchType]);

  // helpers
  const initialSearchResponse: SearchResponse = {
    answer: null,
    quotes: null,
    documents: null,
    searchType: selectedSearchType,
  };
  const updateCurrentAnswer = (answer: string) =>
    setSearchResponse((prevState) => ({
      ...(prevState || initialSearchResponse),
      answer,
    }));
  const updateQuotes = (quotes: Record<string, Quote>) =>
    setSearchResponse((prevState) => ({
      ...(prevState || initialSearchResponse),
      quotes,
    }));
  const updateDocs = (documents: DanswerDocument[]) =>
    setSearchResponse((prevState) => ({
      ...(prevState || initialSearchResponse),
      documents,
    }));

  return (
    <div className="relative max-w-[1500px] mx-auto">
      <div className="absolute left-0 ml-24 hidden 2xl:block">
        {connectors.length > 0 && (
          <SourceSelector
            selectedSources={sources}
            setSelectedSources={setSources}
            existingSources={connectors.map((connector) => connector.source)}
          />
        )}
      </div>
      <div className="w-[800px] mx-auto">
        <SearchTypeSelector
          selectedSearchType={selectedSearchType}
          setSelectedSearchType={setSelectedSearchType}
        />

        <SearchBar
          onSearch={async (query) => {
            setIsFetching(true);
            setSearchResponse({
              answer: null,
              quotes: null,
              documents: null,
              searchType: selectedSearchType,
            });

            if (selectedSearchType === SearchType.AI) {
              await aiSearchRequestStreamed({
                query,
                sources,
                updateCurrentAnswer,
                updateQuotes,
                updateDocs,
              });
            } else {
              await keywordSearch({
                query,
                sources,
                updateCurrentAnswer,
                updateQuotes,
                updateDocs,
              });
            }

            setIsFetching(false);
          }}
        />
        <div className="mt-2">
          <SearchResultsDisplay
            searchResponse={searchResponse}
            isFetching={isFetching}
          />
        </div>
      </div>
    </div>
  );
};
