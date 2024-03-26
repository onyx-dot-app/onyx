import { ErrorCallout } from "@/components/ErrorCallout";
import { fetchSS } from "@/lib/utilsSS";
import { Persona } from "../interfaces";
import { PersonaEditor } from "../PersonaEditor";
import { DocumentSet } from "@/lib/types";
import { BackButton } from "@/components/BackButton";
import { Card, Title } from "@tremor/react";
import { DeletePersonaButton } from "./DeletePersonaButton";

export default async function Page({
  params,
}: {
  params: { personaId: string };
}) {
  const [
    personaResponse,
    documentSetsResponse,
    llmOverridesResponse,
    defaultLLMResponse,
  ] = await Promise.all([
    fetchSS(`/persona/${params.personaId}`),
    fetchSS("/manage/document-set"),
    fetchSS("/admin/persona/utils/list-available-models"),
    fetchSS("/admin/persona/utils/default-model"),
  ]);

  if (!personaResponse.ok) {
    return (
      <ErrorCallout
        errorTitle="Something went wrong :("
        errorMsg={`Failed to fetch Persona - ${await personaResponse.text()}`}
      />
    );
  }

  if (!documentSetsResponse.ok) {
    return (
      <ErrorCallout
        errorTitle="Something went wrong :("
        errorMsg={`Failed to fetch document sets - ${await documentSetsResponse.text()}`}
      />
    );
  }

  if (!llmOverridesResponse.ok) {
    return (
      <ErrorCallout
        errorTitle="Something went wrong :("
        errorMsg={`Failed to fetch LLM override options - ${await documentSetsResponse.text()}`}
      />
    );
  }

  if (!defaultLLMResponse.ok) {
    return (
      <ErrorCallout
        errorTitle="Something went wrong :("
        errorMsg={`Failed to fetch default LLM - ${await documentSetsResponse.text()}`}
      />
    );
  }

  const documentSets = (await documentSetsResponse.json()) as DocumentSet[];
  const persona = (await personaResponse.json()) as Persona;
  const llmOverrideOptions = (await llmOverridesResponse.json()) as string[];
  const defaultLLM = (await defaultLLMResponse.json()) as string;

  return (
    <div>
      <BackButton />
      <div className="pb-2 mb-4 flex">
        <h1 className="text-3xl font-bold pl-2">Edit Persona</h1>
      </div>

      <Card>
        <PersonaEditor
          existingPersona={persona}
          documentSets={documentSets}
          llmOverrideOptions={llmOverrideOptions}
          defaultLLM={defaultLLM}
        />
      </Card>

      <div className="mt-12">
        <Title>Delete Persona</Title>
        <div className="flex mt-6">
          <DeletePersonaButton personaId={persona.id} />
        </div>
      </div>
    </div>
  );
}
