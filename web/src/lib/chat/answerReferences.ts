import type { StreamingCitation } from "@/app/app/services/streamingModels";
import type { OnyxDocument } from "@/lib/search/interfaces";
import { transformLinkUri } from "@/lib/utils";
import { escapeMarkdown } from "@opal/utils";

type ReferenceDocument = Pick<
  OnyxDocument,
  "document_id" | "semantic_identifier" | "link"
>;

interface ReferenceLabels {
  title: string;
  unavailableSource: string;
}

export function buildAnswerWithReferences(
  answer: string,
  citations: readonly StreamingCitation[],
  documents: readonly ReferenceDocument[],
  labels: ReferenceLabels
): string {
  const documentsById = new Map<string, ReferenceDocument>();
  for (const document of documents) {
    if (!documentsById.has(document.document_id)) {
      documentsById.set(document.document_id, document);
    }
  }
  const citedIds = new Set(citations.map((citation) => citation.document_id));
  const references = Array.from(citedIds, (id) => {
    const document = documentsById.get(id);
    const title = escapeMarkdown(
      document?.semantic_identifier?.trim() || labels.unavailableSource
    );
    const link = document?.link ? transformLinkUri(document.link) : null;
    // Relative links cannot resolve outside Onyx. Never create a sharing URL.
    if (!link || !URL.canParse(link)) return `- ${title}`;

    const destination = link
      .replace(/&/g, "&amp;")
      .replace(/[<>\\\s]/g, (character) => encodeURIComponent(character));
    return `- [${title}](<${destination}>)`;
  });

  if (references.length === 0) return answer;
  return `${answer.trimEnd()}\n\n## ${escapeMarkdown(labels.title)}\n\n${references.join("\n")}`;
}
