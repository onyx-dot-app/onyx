import { Persona } from "@/app/admin/assistants/interfaces";
import { DocumentSetSummary, ValidSources } from "./types";
import { getSourcesForPersona } from "./sources";

export function computeAvailableFilters({
  selectedPersona,
  availableSources,
  availableDocumentSets,
}: {
  selectedPersona: Persona | undefined | null;
  availableSources: ValidSources[];
  availableDocumentSets: DocumentSetSummary[];
}): [ValidSources[], DocumentSetSummary[]] {
  const finalAvailableSources =
    selectedPersona && selectedPersona.document_sets.length
      ? getSourcesForPersona(selectedPersona)
      : availableSources;

  // only display document sets that are available to the persona
  // in filters
  const personaDocumentSetIds =
    selectedPersona && selectedPersona.document_sets.length
      ? selectedPersona.document_sets.map((documentSet) => documentSet.id)
      : null;
  const finalAvailableDocumentSets = personaDocumentSetIds
    ? availableDocumentSets.filter((documentSet) =>
        personaDocumentSetIds.includes(documentSet.id)
      )
    : availableDocumentSets;

  return [finalAvailableSources, finalAvailableDocumentSets];
}
