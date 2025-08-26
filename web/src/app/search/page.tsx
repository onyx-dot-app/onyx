"use client";

import React, { useState, useEffect, useMemo } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useLlmManager } from "@/lib/hooks";
import { OnyxLogoTypeIcon } from "@/components/icons/icons";
import SearchInputBar from "@/components-2/Search/SearchInputBar";
import SearchSuggestions from "@/components-2/Search/SearchSuggestions";
import { useChatContext } from "@/components/context/ChatContext";
import { SavedSearchDoc } from "./interfaces";
import SearchResultItem from "@/components-2/Search/SearchResultItem";
import { Separator } from "@/components/ui/separator";
import { Calendar } from "@/components/ui/calendar";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Button } from "@/components/ui/button";
import { CalendarIcon, ChevronDownIcon, Users, Tag } from "lucide-react";
import { format } from "date-fns";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

interface FilterDropdownProps {
  selectedValue: string | null;
  options: string[];
  onSelect: (value: string | null) => void;
  allItemsLabel: string;
  icon?: React.ReactNode;
}

function FilterDropdown({
  selectedValue,
  options,
  onSelect,
  allItemsLabel,
  icon,
}: FilterDropdownProps) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost">
          {icon && <div className="mr-1 h-4 w-4 text-neutral-400">{icon}</div>}
          <p className="text-neutral-400">{selectedValue || allItemsLabel}</p>
          <ChevronDownIcon className="h-4 w-4 text-neutral-400" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent>
        <DropdownMenuItem onClick={() => onSelect(null)}>
          {allItemsLabel}
        </DropdownMenuItem>
        {options.map((option) => (
          <DropdownMenuItem key={option} onClick={() => onSelect(option)}>
            {option}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

type PageProps = {
  searchParams: Promise<{ [key: string]: string }>;
};

type DateRange =
  | {
      from: Date;
      to: Date;
    }
  | undefined;

export default function Page(_props: PageProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryParam = searchParams?.get("query");

  // We only display the "starting page" when we have no query parameter set.
  // Otherwise, we display the results.
  const shouldDisplayStartingPage = queryParam === null;

  // Initialize query from URL parameter
  const [query, setQuery] = useState<string | null>(queryParam);
  const [searchResults, setSearchResults] = useState<SavedSearchDoc[]>([]);
  const { llmProviders } = useChatContext();
  const llmManager = useLlmManager(llmProviders);

  // Filter states
  const [dateRange, setDateRange] = useState<DateRange>(undefined);
  const [selectedPrimaryOwner, setSelectedPrimaryOwner] = useState<
    string | null
  >(null);
  const [selectedTag, setSelectedTag] = useState<string | null>(null);

  // Extract unique primary owners and tags from search results
  const uniquePrimaryOwners = useMemo(() => {
    const owners = new Set<string>();
    searchResults.forEach((doc) => {
      if (doc.primary_owners) {
        doc.primary_owners.forEach((owner) => owners.add(owner));
      }
    });
    return Array.from(owners).sort();
  }, [searchResults]);

  const uniqueTags = useMemo(() => {
    const tags = new Set<string>();
    searchResults.forEach((doc) => {
      if (doc.tags) {
        doc.tags.forEach((tag) => tags.add(tag));
      }
    });
    return Array.from(tags).sort();
  }, [searchResults]);

  // Filter the search results based on selected filters
  const filteredSearchResults = useMemo(() => {
    return searchResults.filter((doc) => {
      // Filter by date range
      if (dateRange?.from && dateRange?.to) {
        const docDate = new Date(doc.updated_at || 0);
        if (docDate < dateRange.from || docDate > dateRange.to) {
          return false;
        }
      }

      // Filter by primary owner
      if (selectedPrimaryOwner) {
        if (
          !doc.primary_owners ||
          !doc.primary_owners.includes(selectedPrimaryOwner)
        ) {
          return false;
        }
      }

      // Filter by tag
      if (selectedTag) {
        if (!doc.tags || !doc.tags.includes(selectedTag)) {
          return false;
        }
      }

      return true;
    });
  }, [searchResults, dateRange, selectedPrimaryOwner, selectedTag]);

  // Sync query state with URL parameter changes
  useEffect(() => {
    if (queryParam !== query) {
      setQuery(queryParam);
      if (queryParam) {
        handleSubmit(queryParam);
      }
    }
  }, [searchParams]);

  const handleSubmit = async (searchQuery: string) => {
    if (!searchQuery) {
      return;
    }

    // Update URL with the query parameter
    const newSearchParams = new URLSearchParams(searchParams?.toString() || "");
    newSearchParams.set("query", searchQuery);
    router.push(`/search?${newSearchParams.toString()}`);

    // Clear all filters when starting a new search
    setDateRange(undefined);
    setSelectedPrimaryOwner(null);
    setSelectedTag(null);

    setSearchResults([]);

    try {
      const llm_override =
        llmManager.currentLlm.modelName || llmManager.temperature
          ? {
              temperature: llmManager.temperature,
              model_provider: llmManager.currentLlm.provider,
              model_version: llmManager.currentLlm.modelName,
            }
          : null;

      const response = await fetch("/api/search/send-query", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          query: searchQuery.trim(),
          llm_override,
        }),
      });

      if (!response.ok) {
        throw new Error(`Search request failed: ${response.statusText}`);
      }

      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error("No response body available");
      }

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();

        if (done) {
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (line.trim()) {
            try {
              const data = JSON.parse(line);
              if (data.error) {
                console.error("Search error:", data.error);
                return;
              }

              const searchDoc = data as SavedSearchDoc;
              setSearchResults((prev) => [...prev, searchDoc]);
            } catch (e) {
              console.warn("Failed to parse streaming data:", line);
            }
          }
        }
      }
    } catch (error) {
      console.error("Search submission error:", error);
    }
  };

  const handleSearchSubmit = () => {
    if (query) {
      handleSubmit(query);
    }
  };

  const handleSuggestionClick = (suggestion: string) => {
    setQuery(suggestion);
    handleSubmit(suggestion);
  };

  const handleClear = () => {
    setQuery(null);
  };

  return (
    <div className="flex flex-col flex-1 items-center justify-center bg-background">
      <div className="w-full px-4 flex flex-col items-center justify-center h-full overflow-y-scroll">
        {/* Onyx Logo */}
        {shouldDisplayStartingPage && (
          <div className="flex justify-center pb-8 flex-shrink-0">
            <OnyxLogoTypeIcon size={200} />
          </div>
        )}

        {/* Search Bar */}
        <div className="w-full max-w-3xl">
          <SearchInputBar
            onSubmit={handleSearchSubmit}
            value={query}
            onChange={setQuery}
            onClear={handleClear}
          />
          {shouldDisplayStartingPage && (
            <div className="w-full pt-6 flex-shrink-0">
              <SearchSuggestions onSuggestionClick={handleSuggestionClick} />
            </div>
          )}
        </div>

        {/* Search Results */}
        {!shouldDisplayStartingPage && (
          <div className="w-full max-w-3xl flex-1 min-h-0 flex flex-col">
            <div className="flex flex-col flex-shrink-0 pt-6">
              <div className="flex items-center gap-2">
                {/* Date Range Picker */}
                <Popover>
                  <PopoverTrigger asChild>
                    <Button variant="ghost" className="text-neutral-400">
                      <CalendarIcon className="mr-1 h-4 w-4 text-neutral-400" />
                      <p className="text-neutral-400">
                        {dateRange?.from ? (
                          dateRange.to ? (
                            <>
                              {format(dateRange.from, "LLL dd, y")} -{" "}
                              {format(dateRange.to, "LLL dd, y")}
                            </>
                          ) : (
                            format(dateRange.from, "LLL dd, y")
                          )
                        ) : (
                          "All Time"
                        )}
                      </p>
                      <ChevronDownIcon className="ml-auto h-4 w-4 text-neutral-400" />
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent className="w-auto p-0" align="start">
                    <Calendar
                      initialFocus
                      mode="range"
                      defaultMonth={dateRange?.from}
                      selected={dateRange}
                      onSelect={(range) => {
                        if (range?.from) {
                          if (range.to) {
                            setDateRange({ from: range.from, to: range.to });
                          } else {
                            const to = new Date(range.from);
                            const from = new Date(to.setDate(to.getDate() - 1));
                            setDateRange({ from, to });
                          }
                        }
                      }}
                      numberOfMonths={2}
                    />
                    <div className="border-t p-3">
                      <Button
                        variant="ghost"
                        className="w-full justify-start"
                        onClick={() => {
                          const from = new Date();
                          from.setDate(from.getDate() - 30);
                          setDateRange({ from, to: new Date() });
                        }}
                      >
                        Last 30 days
                      </Button>
                      <Button
                        variant="ghost"
                        className="w-full justify-start"
                        onClick={() => {
                          const from = new Date();
                          from.setDate(from.getDate() - 7);
                          setDateRange({ from, to: new Date() });
                        }}
                      >
                        Last 7 days
                      </Button>
                      <Button
                        variant="ghost"
                        className="w-full justify-start"
                        onClick={() => setDateRange(undefined)}
                      >
                        Clear
                      </Button>
                    </div>
                  </PopoverContent>
                </Popover>

                {/* Primary Owner Picker */}
                <FilterDropdown
                  selectedValue={selectedPrimaryOwner}
                  options={uniquePrimaryOwners}
                  onSelect={setSelectedPrimaryOwner}
                  allItemsLabel="All owners"
                  icon={<Users className="h-4 w-4" />}
                />

                {/* Tag Picker */}
                <FilterDropdown
                  selectedValue={selectedTag}
                  options={uniqueTags}
                  onSelect={setSelectedTag}
                  allItemsLabel="All tags"
                  icon={<Tag className="h-4 w-4" />}
                />
              </div>
            </div>

            <Separator />

            <div className="flex flex-1 flex-col gap-y-2 pb-10">
              {filteredSearchResults.map((doc, index) => (
                <div key={index}>
                  <SearchResultItem
                    doc={doc}
                    onClick={() => {
                      if (doc.link) {
                        window.open(doc.link, "_blank");
                      }
                    }}
                  />
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
