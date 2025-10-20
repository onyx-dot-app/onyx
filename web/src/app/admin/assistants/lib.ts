import { LLMProviderView } from "../configuration/llm/interfaces";
import { MinimalPersonaSnapshot, Persona, StarterMessage } from "./interfaces";

interface PersonaUpsertRequest {
  name: string;
  description: string;
  system_prompt: string;
  task_prompt: string;
  datetime_aware: boolean;
  document_set_ids: number[];
  num_chunks: number | null;
  is_public: boolean;
  recency_bias: string;
  llm_filter_extraction: boolean;
  llm_relevance_filter: boolean | null;
  llm_model_provider_override: string | null;
  llm_model_version_override: string | null;
  starter_messages: StarterMessage[] | null;
  users?: string[];
  groups: number[];
  tool_ids: number[];
  icon_color: string | null;
  icon_shape: number | null;
  remove_image?: boolean;
  uploaded_image_id: string | null;
  search_start_date: Date | null;
  is_default_persona: boolean;
  display_priority: number | null;
  label_ids: number[] | null;
  user_file_ids: string[] | null;
}

export interface PersonaUpsertParameters {
  name: string;
  description: string;
  system_prompt: string;
  task_prompt: string;
  datetime_aware: boolean;
  document_set_ids: number[];
  num_chunks: number | null;
  is_public: boolean;
  llm_relevance_filter: boolean | null;
  llm_model_provider_override: string | null;
  llm_model_version_override: string | null;
  starter_messages: StarterMessage[] | null;
  users?: string[];
  groups: number[];
  tool_ids: number[];
  icon_color: string | null;
  icon_shape: number | null;
  remove_image?: boolean;
  search_start_date: Date | null;
  uploaded_image: File | null;
  is_default_persona: boolean;
  label_ids: number[] | null;
  user_file_ids: string[];
}

export const createPersonaLabel = (name: string) => {
  return fetch("/api/persona/labels", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ name }),
  });
};

export const deletePersonaLabel = (labelId: number) => {
  return fetch(`/api/admin/persona/label/${labelId}`, {
    method: "DELETE",
    headers: {
      "Content-Type": "application/json",
    },
  });
};

export const updatePersonaLabel = (
  id: number,
  name: string
): Promise<Response> => {
  return fetch(`/api/admin/persona/label/${id}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      label_name: name,
    }),
  });
};

function buildPersonaUpsertRequest(
  creationRequest: PersonaUpsertParameters,
  uploaded_image_id: string | null
): PersonaUpsertRequest {
  const {
    name,
    description,
    system_prompt,
    task_prompt,
    document_set_ids,
    num_chunks,
    is_public,
    groups,
    datetime_aware,
    users,
    tool_ids,
    icon_color,
    icon_shape,
    remove_image,
    search_start_date,
    user_file_ids,
  } = creationRequest;

  return {
    name,
    description,
    system_prompt,
    task_prompt,
    document_set_ids,
    num_chunks,
    is_public,
    uploaded_image_id,
    groups,
    users,
    tool_ids,
    icon_color,
    icon_shape,
    remove_image,
    search_start_date,
    datetime_aware,
    is_default_persona: creationRequest.is_default_persona ?? false,
    recency_bias: "base_decay",
    llm_filter_extraction: false,
    llm_relevance_filter: creationRequest.llm_relevance_filter ?? null,
    llm_model_provider_override:
      creationRequest.llm_model_provider_override ?? null,
    llm_model_version_override:
      creationRequest.llm_model_version_override ?? null,
    starter_messages: creationRequest.starter_messages ?? null,
    display_priority: null,
    label_ids: creationRequest.label_ids ?? null,
    user_file_ids: user_file_ids ?? null,
  };
}

export async function uploadFile(file: File): Promise<string | null> {
  const formData = new FormData();
  formData.append("file", file);
  const response = await fetch("/api/admin/persona/upload-image", {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    console.error("Failed to upload file");
    return null;
  }

  const responseJson = await response.json();
  return responseJson.file_id;
}

export async function createPersona(
  personaUpsertParams: PersonaUpsertParameters
): Promise<Response | null> {
  let fileId = null;
  if (personaUpsertParams.uploaded_image) {
    fileId = await uploadFile(personaUpsertParams.uploaded_image);
    if (!fileId) {
      return null;
    }
  }
  const createPersonaResponse = await fetch("/api/persona", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(
      buildPersonaUpsertRequest(personaUpsertParams, fileId)
    ),
  });

  return createPersonaResponse;
}

export async function updatePersona(
  id: number,
  personaUpsertParams: PersonaUpsertParameters
): Promise<Response | null> {
  let fileId = null;
  if (personaUpsertParams.uploaded_image) {
    fileId = await uploadFile(personaUpsertParams.uploaded_image);
    if (!fileId) {
      return null;
    }
  }

  const updatePersonaResponse = await fetch(`/api/persona/${id}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(
      buildPersonaUpsertRequest(personaUpsertParams, fileId)
    ),
  });

  return updatePersonaResponse;
}

export function deletePersona(personaId: number) {
  return fetch(`/api/persona/${personaId}`, {
    method: "DELETE",
  });
}

function smallerNumberFirstComparator(a: number, b: number) {
  return a > b ? 1 : -1;
}

function closerToZeroNegativesFirstComparator(a: number, b: number) {
  if (a < 0 && b > 0) {
    return -1;
  }
  if (a > 0 && b < 0) {
    return 1;
  }

  const absA = Math.abs(a);
  const absB = Math.abs(b);

  if (absA === absB) {
    return a > b ? 1 : -1;
  }

  return absA > absB ? 1 : -1;
}

export function personaComparator(
  a: MinimalPersonaSnapshot | Persona,
  b: MinimalPersonaSnapshot | Persona
) {
  if (a.display_priority === null && b.display_priority === null) {
    return closerToZeroNegativesFirstComparator(a.id, b.id);
  }

  if (a.display_priority !== b.display_priority) {
    if (a.display_priority === null) {
      return 1;
    }
    if (b.display_priority === null) {
      return -1;
    }

    return smallerNumberFirstComparator(a.display_priority, b.display_priority);
  }

  return closerToZeroNegativesFirstComparator(a.id, b.id);
}

export const togglePersonaDefault = async (
  personaId: number,
  isDefault: boolean
) => {
  const response = await fetch(`/api/admin/persona/${personaId}/default`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      is_default_persona: !isDefault,
    }),
  });
  return response;
};

export const togglePersonaVisibility = async (
  personaId: number,
  isVisible: boolean
) => {
  const response = await fetch(`/api/admin/persona/${personaId}/visible`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      is_visible: !isVisible,
    }),
  });
  return response;
};

export const togglePersonaPublicStatus = async (
  personaId: number,
  isPublic: boolean
) => {
  const response = await fetch(`/api/persona/${personaId}/public`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      is_public: isPublic,
    }),
  });
  return response;
};

export function checkPersonaRequiresImageGeneration(persona: Persona) {
  for (const tool of persona.tools) {
    if (tool.name === "ImageGenerationTool") {
      return true;
    }
  }
  return false;
}

export function providersContainImageGeneratingSupport(
  providers: LLMProviderView[]
) {
  return providers.some((provider) => provider.provider === "openai");
}
