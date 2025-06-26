import { FullPersona, Persona } from "@/app/admin/assistants/interfaces";
import { CCPairBasicInfo, DocumentSet, User } from "../types";
import { getCurrentUserSS } from "../userSS";
import { fetchSS } from "../utilsSS";
import {
  LLMProviderView,
  getProviderIcon,
} from "@/app/admin/configuration/llm/interfaces";
import { ToolSnapshot } from "../tools/interfaces";
import { fetchToolsSS } from "../tools/fetchTools";
import { KnowledgeMapCreationRequest } from "@/app/admin/documents/knowledge_maps/lib";

export async function fetchAssistantEditorInfoSS(
  personaId?: number | string
): Promise<
  | [
      {
        ccPairs: CCPairBasicInfo[];
        documentSets: DocumentSet[];
        llmProviders: LLMProviderView[];
        knowledgeMaps: KnowledgeMapCreationRequest[];
        user: User | null;
        existingPersona: FullPersona | null;
        tools: ToolSnapshot[];
      },
      null
    ]
  | [null, string]
> {
  const tasks = [
    fetchSS("/manage/connector-status"),
    fetchSS("/manage/document-set"),
    fetchSS("/llm/provider"),
    fetchSS("/knowledge/get"),
    // duplicate fetch, but shouldn't be too big of a deal
    // this page is not a high traffic page
    getCurrentUserSS(),
    fetchToolsSS(),
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
    knowledgeMapsResponse,
    user,
    toolsResponse,
    personaResponse,
  ] = (await Promise.all(tasks)) as [
    Response,
    Response,
    Response,
    Response,
    User | null,
    ToolSnapshot[] | null,
    Response | null
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

  if (!toolsResponse) {
    return [null, `Failed to fetch tools`];
  }

  if (!llmProvidersResponse.ok) {
    return [
      null,
      `Failed to fetch LLM providers - ${await llmProvidersResponse.text()}`,
    ];
  }

  const llmProviders = (await llmProvidersResponse.json()) as LLMProviderView[];
  if (!knowledgeMapsResponse.ok) {
    return [
      null,
      `Не удалось получить данные - ${await knowledgeMapsResponse.text()}`,
    ];
  }

  const knowledgeMaps =
    (await knowledgeMapsResponse.json()) as KnowledgeMapCreationRequest[];
  if (personaId && personaResponse && !personaResponse.ok) {
    return [null, `Failed to fetch Persona - ${await personaResponse.text()}`];
  }

  for (const provider of llmProviders) {
    provider.icon = getProviderIcon(provider.provider);
  }

  const existingPersona = personaResponse
    ? ((await personaResponse.json()) as FullPersona)
    : null;

  let error: string | null = null;
  if (existingPersona?.builtin_persona) {
    return [null, "cannot update builtin persona"];
  }

  return (
    error || [
      {
        ccPairs,
        documentSets,
        llmProviders,
        knowledgeMaps,
        user,
        existingPersona,
        tools: toolsResponse,
      },
      null,
    ]
  );
}
