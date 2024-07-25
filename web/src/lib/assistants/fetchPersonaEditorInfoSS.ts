import { Persona } from "@/app/admin/assistants/interfaces";
import { CCPairBasicInfo, DocumentSet, User } from "../types";
import { getCurrentUserSS } from "../userSS";
import { fetchSS } from "../utilsSS";
import { FullLLMProvider } from "@/app/admin/models/llm/interfaces";
import { ToolSnapshot } from "../tools/interfaces";
import { fetchToolsSS } from "../tools/fetchTools";
import { IconManifestType } from "react-icons/lib";
import {
  OpenAIIcon,
  AnthropicIcon,
  AWSIcon,
  AzureIcon,
  OpenSourceIcon,
} from "@/components/icons/icons";

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
        tools: ToolSnapshot[];
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
    user,
    toolsResponse,
    personaResponse,
  ] = (await Promise.all(tasks)) as [
    Response,
    Response,
    Response,
    User | null,
    ToolSnapshot[] | null,
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

  if (!toolsResponse) {
    return [null, `Failed to fetch tools`];
  }

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

  for (const provider of llmProviders) {
    if (provider.provider == "openai") {
      provider.icon = OpenAIIcon;
    } else if (provider.provider == "anthropic") {
      provider.icon = AnthropicIcon;
    } else if (provider.provider == "bedrock") {
      provider.icon = AzureIcon;
    } else if (provider.provider == "azure") {
      provider.icon = AWSIcon;
    } else {
      provider.icon = OpenSourceIcon;
    }
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
      tools: toolsResponse,
    },
    null,
  ];
}
