import { Persona } from "@/app/admin/assistants/interfaces";
import { CCPairBasicInfo, DocumentSet, User } from "../types";
import { getCurrentUserSS } from "../userSS";
import { fetchSS } from "../utilsSS";

export async function fetchAssistantEditorInfoSS(
  personaId?: number | string
): Promise<
  | [
      {
        ccPairs: CCPairBasicInfo[];
        documentSets: DocumentSet[];
        llmOverrideOptions: string[];
        defaultLLM: string;
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
    fetchSS("/persona/utils/list-available-models"),
    fetchSS("/persona/utils/default-model"),
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
    llmOverridesResponse,
    defaultLLMResponse,
    user,
    personaResponse,
  ] = (await Promise.all(tasks)) as [
    Response,
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

  if (!llmOverridesResponse.ok) {
    return [
      null,
      `Failed to fetch LLM override options - ${await llmOverridesResponse.text()}`,
    ];
  }
  const llmOverrideOptions = (await llmOverridesResponse.json()) as string[];

  if (!defaultLLMResponse.ok) {
    return [
      null,
      `Failed to fetch default LLM - ${await defaultLLMResponse.text()}`,
    ];
  }
  const defaultLLM = (await defaultLLMResponse.json()) as string;

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
      llmOverrideOptions,
      defaultLLM,
      user,
      existingPersona,
    },
    null,
  ];
}
