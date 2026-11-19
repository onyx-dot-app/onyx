"use client";

import { useTranslations } from "next-intl";
import { Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { SvgSearch } from "@opal/icons";
import { BlinkingBar } from "@/app/app/message/BlinkingBar";
import { ValidSources } from "@/lib/connectors/types/source";
import {
  SearchChipList,
  type SourceInfo,
} from "@/lib/timeline/components/bodies/SearchChipList";

export const INITIAL_QUERIES_TO_SHOW = 3;
export const QUERIES_PER_EXPANSION = 5;
export const INITIAL_RESULTS_TO_SHOW = 3;
export const RESULTS_PER_EXPANSION = 10;

export function queryToSourceInfo(query: string, index: number): SourceInfo {
  return {
    id: `query-${index}`,
    title: query,
    sourceType: ValidSources.Web,
    icon: SvgSearch,
  };
}

interface RetrievalBodyProps {
  /** What the step searched for, shown as query chips. */
  queries: string[];
  /** What the step read, shown as source chips under "Reading". */
  results: SourceInfo[];
  /** A finished step with no results says so; a running one shows a cursor. */
  isComplete: boolean;
  /** Show only the results, without queries or the "Reading" label. */
  compact?: boolean;
}

/**
 * The body of a retrieval step (search, fetch): the queries, then the sources
 * it read. Shared by chat and Craft.
 */
export function RetrievalBody({
  queries,
  results,
  isComplete,
  compact = false,
}: RetrievalBodyProps) {
  const t = useTranslations("chat.messages.timeline");

  return (
    <Section alignItems="stretch" gap={0} height="auto">
      {!compact && (
        <SearchChipList
          items={queries}
          initialCount={INITIAL_QUERIES_TO_SHOW}
          expansionCount={QUERIES_PER_EXPANSION}
          getKey={(_, index) => index}
          toSourceInfo={queryToSourceInfo}
          emptyState={!isComplete ? <BlinkingBar /> : undefined}
          showDetailsCard={false}
          isQuery={true}
        />
      )}

      {(results.length > 0 || queries.length > 0) && (
        <>
          {!compact && (
            <Text as="p" font="main-ui-muted" color="text-04">
              {t("internalSearch.reading.status")}
            </Text>
          )}
          <SearchChipList
            items={results}
            initialCount={INITIAL_RESULTS_TO_SHOW}
            expansionCount={RESULTS_PER_EXPANSION}
            getKey={(source) => source.id}
            toSourceInfo={(source) => source}
            onClick={(source) => {
              if (source.sourceUrl) {
                window.open(source.sourceUrl, "_blank", "noopener,noreferrer");
              }
            }}
            emptyState={
              !isComplete ? (
                <BlinkingBar />
              ) : (
                <Text as="p" font="main-ui-muted" color="text-03">
                  {t("internalSearch.noResults.text")}
                </Text>
              )
            }
          />
        </>
      )}
    </Section>
  );
}
