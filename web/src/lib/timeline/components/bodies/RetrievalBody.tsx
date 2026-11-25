"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Badge, Tag, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { SvgSearch } from "@opal/icons";
import { ValidSources } from "@/lib/connectors/types/source";
import { getSourceMetadata } from "@/lib/connectors/utils";
import type { IconFunctionComponent } from "@opal/types";
import { openExternalLink } from "@/lib/search/utils";
import type { SourceInfo } from "@/lib/timeline/components/bodies/SearchChipList";
import { faviconIcon } from "@/lib/timeline/components/bodies/favicon";

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

/** A source's own icon, a web page's favicon, else its connector's logo. */
function sourceIcon(source: SourceInfo): IconFunctionComponent {
  if (source.icon) return source.icon;
  if (source.sourceType === ValidSources.Web && source.sourceUrl) {
    return faviconIcon(source.sourceUrl);
  }
  return getSourceMetadata(source.sourceType).icon;
}

interface RetrievalBodyProps {
  /** What the step searched for, shown as query chips. */
  queries: string[];
  /**
   * What the step read, shown as source chips under "Read". `null` for a
   * step that only searches; another step reads its results.
   */
  results: SourceInfo[] | null;
  /** A finished step with no results says so; a running one shows a cursor. */
  isComplete: boolean;
  /** Show only the results, without queries or the "Read" label. */
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
  const [visibleQueries, setVisibleQueries] = useState(INITIAL_QUERIES_TO_SHOW);
  const [visibleResults, setVisibleResults] = useState(INITIAL_RESULTS_TO_SHOW);
  const hiddenQueries = Math.max(0, queries.length - visibleQueries);

  const showResults =
    results !== null && (compact || results.length > 0 || queries.length > 0);
  const resultList = results ?? [];
  const hiddenResults = Math.max(0, resultList.length - visibleResults);

  return (
    // 0.25rem between the queries, "Read" and the results, and between the
    // labels in each row.
    <Section alignItems="stretch" gap={1} height="auto">
      {!compact &&
        (queries.length > 0 ? (
          <Section
            flexDirection="row"
            justifyContent="start"
            height="fit"
            gap={1}
            wrap
          >
            {queries.slice(0, visibleQueries).map((query, index) => (
              <Badge key={index} icon={SvgSearch} title={query} size={6} />
            ))}
            {hiddenQueries > 0 && (
              <Tag
                title={t("searchChips.showMore.label", {
                  count: hiddenQueries,
                })}
                onClick={() =>
                  setVisibleQueries((count) => count + QUERIES_PER_EXPANSION)
                }
              />
            )}
          </Section>
        ) : null)}

      {showResults && !compact && (
        <Text as="p" font="secondary-action" color="text-03">
          {t("internalSearch.read.label")}
        </Text>
      )}

      {showResults &&
        (resultList.length > 0 ? (
          <Section
            flexDirection="row"
            justifyContent="start"
            height="fit"
            gap={1}
            wrap
          >
            {resultList.slice(0, visibleResults).map((source) => {
              const url = source.sourceUrl;
              return (
                <Tag
                  key={source.id}
                  icon={sourceIcon(source)}
                  title={source.title}
                  truncate
                  onClick={url ? () => openExternalLink(url) : undefined}
                />
              );
            })}
            {hiddenResults > 0 && (
              <Tag
                title={t("searchChips.showMore.label", {
                  count: hiddenResults,
                })}
                onClick={() =>
                  setVisibleResults((count) => count + RESULTS_PER_EXPANSION)
                }
              />
            )}
          </Section>
        ) : isComplete ? (
          <Text as="p" font="main-ui-muted" color="text-03">
            {t("internalSearch.noResults.text")}
          </Text>
        ) : null)}
    </Section>
  );
}
