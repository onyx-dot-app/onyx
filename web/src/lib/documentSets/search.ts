import { getSourceMetadata } from "@/lib/sources";
import type {
  CCPairSummary,
  DocumentSetSummary,
  FederatedConnectorSummary,
} from "@/lib/types";

/** A `[start, end)` slice of a string. */
export type TextRange = [number, number];

/** Splits a search query into lowercase terms. */
export function getSearchTerms(query: string): string[] {
  return query.toLowerCase().split(/\s+/).filter(Boolean);
}

/** The source name a search matches a connector by, such as "Google Drive". */
export function getConnectorSourceName(ccPair: CCPairSummary): string {
  return getSourceMetadata(ccPair.source).displayName;
}

/** The string values of a federated connector's entities, such as channel names. */
export function getEntityStrings(
  federatedConnector: FederatedConnectorSummary
): string[] {
  return Object.values(federatedConnector.entities).flatMap((value) => {
    if (typeof value === "string") return [value];
    if (Array.isArray(value)) {
      return value.filter((item): item is string => typeof item === "string");
    }
    return [];
  });
}

function getSearchableFields(documentSet: DocumentSetSummary): string[] {
  const fields = [documentSet.name, documentSet.description ?? ""];
  for (const ccPair of documentSet.cc_pair_summaries) {
    fields.push(ccPair.name, getConnectorSourceName(ccPair));
  }
  for (const federatedConnector of documentSet.federated_connector_summaries) {
    fields.push(
      federatedConnector.name,
      ...getEntityStrings(federatedConnector)
    );
  }
  return fields.map((field) => field.toLowerCase());
}

/**
 * Keeps the document sets that match every term of `query`. Each term can match
 * the name, the description, a connector's name or source, or a federated
 * connector's name or entities. Sets whose name holds every term come first.
 * The order is otherwise kept.
 */
export function searchDocumentSets(
  documentSets: DocumentSetSummary[],
  query: string
): DocumentSetSummary[] {
  const terms = getSearchTerms(query);
  if (terms.length === 0) return documentSets;

  const nameMatches: DocumentSetSummary[] = [];
  const otherMatches: DocumentSetSummary[] = [];
  for (const documentSet of documentSets) {
    const fields = getSearchableFields(documentSet);
    if (!terms.every((term) => fields.some((field) => field.includes(term)))) {
      continue;
    }
    const name = documentSet.name.toLowerCase();
    if (terms.every((term) => name.includes(term))) {
      nameMatches.push(documentSet);
    } else {
      otherMatches.push(documentSet);
    }
  }
  return [...nameMatches, ...otherMatches];
}

/** Whether a term matches the connector's source but not its name. */
export function matchesSourceOnly(
  ccPair: CCPairSummary,
  terms: string[]
): boolean {
  const name = ccPair.name.toLowerCase();
  const sourceName = getConnectorSourceName(ccPair).toLowerCase();
  return terms.some(
    (term) => sourceName.includes(term) && !name.includes(term)
  );
}

/** The sorted, merged ranges of `text` where a term occurs. */
export function findTermRanges(text: string, terms: string[]): TextRange[] {
  const haystack = text.toLowerCase();
  // A few characters change length when lowercased, which would shift the ranges.
  if (haystack.length !== text.length) return [];

  const ranges: TextRange[] = [];
  for (const term of terms) {
    let start = haystack.indexOf(term);
    while (start !== -1) {
      ranges.push([start, start + term.length]);
      start = haystack.indexOf(term, start + term.length);
    }
  }
  ranges.sort((a, b) => a[0] - b[0]);

  const merged: TextRange[] = [];
  for (const [start, end] of ranges) {
    const last = merged[merged.length - 1];
    if (last && start <= last[1]) {
      last[1] = Math.max(last[1], end);
    } else {
      merged.push([start, end]);
    }
  }
  return merged;
}
