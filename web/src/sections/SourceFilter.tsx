"use client";

import { useMemo } from "react";
import { SearchDocWithContent } from "@/lib/search/searchApi";
import { SourceMetadata } from "@/lib/search/interfaces";
import { getSourceMetadata } from "@/lib/sources";
import { ValidSources } from "@/lib/types";
import { SourceIcon } from "@/components/SourceIcon";
import Text from "@/refresh-components/texts/Text";
import Separator from "@/refresh-components/Separator";
import LineItem from "@/refresh-components/buttons/LineItem";

export interface SourceFilterProps {
  /** Search results to extract sources from */
  results: SearchDocWithContent[];
  /** Currently selected sources */
  selectedSources: string[];
  /** Callback when source selection changes */
  onSourceChange: (sources: string[]) => void;
}

/**
 * Sidebar component for filtering search results by source.
 */
export default function SourceFilter({
  results,
  selectedSources,
  onSourceChange,
}: SourceFilterProps) {
  // Extract unique sources with metadata
  const sourcesWithMeta = useMemo(() => {
    const sourceMap = new Map<
      string,
      { meta: SourceMetadata; count: number }
    >();

    for (const doc of results) {
      if (doc.source_type) {
        const existing = sourceMap.get(doc.source_type);
        if (existing) {
          existing.count++;
        } else {
          sourceMap.set(doc.source_type, {
            meta: getSourceMetadata(doc.source_type as ValidSources),
            count: 1,
          });
        }
      }
    }

    return Array.from(sourceMap.entries())
      .map(([source, data]) => ({
        source,
        ...data,
      }))
      .sort((a, b) => b.count - a.count);
  }, [results]);

  const handleToggle = (source: string) => {
    if (selectedSources.includes(source)) {
      onSourceChange(selectedSources.filter((s) => s !== source));
    } else {
      onSourceChange([...selectedSources, source]);
    }
  };

  return (
    <div className="h-full w-[15rem] overflow-y-auto py-4 flex flex-col gap-4 px-4">
      <div className="py-4 h-[2.75rem] px-2">
        <Text text03 mainUiMuted>
          {results.length} Results
        </Text>
      </div>

      <Separator noPadding />

      <div className="flex flex-col gap-1">
        {/* Individual sources */}
        {sourcesWithMeta.map(({ source, meta, count }) => (
          <LineItem
            icon={(props) => (
              <SourceIcon
                sourceType={source as ValidSources}
                iconSize={16}
                {...props}
              />
            )}
            onClick={() => handleToggle(source)}
            selected={selectedSources.includes(source)}
            emphasized
            rightChildren={<Text text03>{count}</Text>}
          >
            {meta.displayName}
          </LineItem>
        ))}
      </div>
    </div>
  );
}
