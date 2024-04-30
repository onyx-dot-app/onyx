import { Persona } from "@/app/admin/assistants/interfaces";
import { CCPairBasicInfo, DocumentSet, User } from "../types";
import { getCurrentUserSS } from "../userSS";
import { fetchSS } from "../utilsSS";
import { FullLLMProvider } from "@/app/admin/models/llm/interfaces";

export async function fetchAssistantEditorInfoSS(
  personaId?: number | string
): Promise<
  | [
      {
        ccPairs: CCPairBasicInfo[];
        documentSets: DocumentSet[];
        llmProviders: FullLLMProvider[];
        user: User | null;
        existingPersona: Persona | null;
      },
      null,
    ]
  | [null, string]
> {
  const tasks = [
    fetchSS("/manage/indexing-status"),
    fetchSS("/manage/document-set"),
    fetchSS("/llm/provider"),
    // duplicate fetch, but shouldn't be too big of a deal
    // this page is not a high traffic page
    getCurrentUserSS(),
  ];
  if (personaId) {
    tasks.push(fetchSS(`/persona/${personaId}`));
  } else {
    tasks.push((async () => null)());
  }

  const [
    ccPairsInfoResponse,
    documentSetsResponse,
    llmProvidersResponse,
    user,
    personaResponse,
  ] = (await Promise.all(tasks)) as [
    Response,
    Response,
    Response,
    User | null,
    Response | null,
  ];

  if (!ccPairsInfoResponse.ok) {
    return [
      null,
      `Failed to fetch connectors - ${await ccPairsInfoResponse.text()}`,
    ];
  }
  const ccPairs = (await ccPairsInfoResponse.json()) as CCPairBasicInfo[];

  if (!documentSetsResponse.ok) {
    return [
      null,
      `Failed to fetch document sets - ${await documentSetsResponse.text()}`,
    ];
  }
  const documentSets = (await documentSetsResponse.json()) as DocumentSet[];

  if (!llmProvidersResponse.ok) {
    return [
      null,
      `Failed to fetch LLM providers - ${await llmProvidersResponse.text()}`,
    ];
  }
  const llmProviders = (await llmProvidersResponse.json()) as FullLLMProvider[];

  if (personaId && personaResponse && !personaResponse.ok) {
    return [null, `Failed to fetch Persona - ${await personaResponse.text()}`];
  }
  const existingPersona = personaResponse
    ? ((await personaResponse.json()) as Persona)
    : null;

  return [
    {
      ccPairs,
      documentSets,
      llmProviders,
      user,
      existingPersona,
    },
    null,
  ];
}
