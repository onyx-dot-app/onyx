import { OnyxDocument } from "@/lib/search/interfaces";
import { SubQuestionDetail } from "@/app/app/interfaces";
import { StreamingCitation } from "@/app/app/services/streamingModels";
import { ValidSources } from "@/lib/types";
import { getSourceDisplayName } from "@/lib/sources";
import { SourceInfo } from "./SourceTagDetailsCard";

const MAX_TITLE_LENGTH = 40;

function truncateText(str: string, maxLength: number): string {
  if (str.length <= maxLength) return str;
  return str.slice(0, maxLength) + "...";
}

/**
 * Convert an OnyxDocument to a SourceInfo object for use with SourceTag
 */
export function documentToSourceInfo(doc: OnyxDocument): SourceInfo {
  const sourceType = doc.source_type as ValidSources;

  return {
    id: doc.document_id,
    title: doc.semantic_identifier || "Unknown",
    sourceType,
    sourceUrl: doc.link,
    description: doc.blurb,
    metadata: doc.updated_at
      ? {
          date: doc.updated_at,
        }
      : undefined,
  };
}

/**
 * Convert a SubQuestionDetail to a SourceInfo object for use with SourceTag
 */
export function questionToSourceInfo(
  question: SubQuestionDetail,
  index: number
): SourceInfo {
  return {
    id: `question-${question.level}-${question.level_question_num}`,
    title: truncateText(question.question, MAX_TITLE_LENGTH),
    sourceType: ValidSources.NotApplicable,
    description: question.answer,
    isQuestion: true,
    questionData: question,
  };
}

/**
 * Convert an array of citations and document map to SourceInfo array
 * Used for end-of-message Sources tag
 */
export function citationsToSourceInfoArray(
  citations: StreamingCitation[],
  documentMap: Map<string, OnyxDocument>
): SourceInfo[] {
  const sources: SourceInfo[] = [];
  const seenDocIds = new Set<string>();

  for (const citation of citations) {
    if (seenDocIds.has(citation.document_id)) continue;

    const doc = documentMap.get(citation.document_id);
    if (doc) {
      seenDocIds.add(citation.document_id);
      sources.push(documentToSourceInfo(doc));
    }
  }

  // Fallback: if no citations but we have documents, use first few documents
  if (sources.length === 0 && documentMap.size > 0) {
    const entries = Array.from(documentMap.entries());
    for (const [, doc] of entries) {
      sources.push(documentToSourceInfo(doc));
      if (sources.length >= 3) break;
    }
  }

  return sources;
}

/**
 * Get a display name for a source, used for inline citations
 */
export function getDisplayNameForSource(doc: OnyxDocument): string {
  const sourceType = doc.source_type as ValidSources;

  if (sourceType === ValidSources.Web || doc.is_internet) {
    return truncateText(doc.semantic_identifier || "", MAX_TITLE_LENGTH);
  }

  return (
    getSourceDisplayName(sourceType) ||
    truncateText(doc.semantic_identifier || "", MAX_TITLE_LENGTH)
  );
}
