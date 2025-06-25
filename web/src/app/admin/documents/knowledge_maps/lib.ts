import { Filters } from "@/lib/search/interfaces";

export const adminSearch = async (query: string, filters: Filters) => {
  const response = await fetch("/api/admin/search", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      query,
      filters,
    }),
  });
  return response;
};

export interface KnowledgeMapCreationRequest {
  name: string;
  description: string;
  document_set_id: number;
  flowise_pipeline_id: string;
  id: number;
  answers: KnowledgeMapAnswer[];
}

export interface KnowledgeMapAnswer {
  id: number;
  document_id: string;
  knowledge_map_id: number;
  topic: string;
  answer: string;
}

export type KnowledgeMapUpdateRequest = KnowledgeMapCreationRequest & {
  id: number;
};

export const createKnowledgeMap = async ({
  name,
  description,
  document_set_id,
  flowise_pipeline_id,
}: KnowledgeMapCreationRequest) => {
  return fetch("/api/knowledge/new", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      name,
      description,
      document_set_id,
      flowise_pipeline_id,
    }),
  });
};

export const updateKnowledgeMap = async ({
  id,
  name,
  description,
  document_set_id,
  flowise_pipeline_id,
}: KnowledgeMapUpdateRequest) => {
  return fetch("/api/knowledge/patch", {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      id,
      name,
      description,
      document_set_id,
      flowise_pipeline_id,
    }),
  });
};

export const deleteKnowledgeMap = async (knowledge_map_id: number) => {
  return fetch(`/api/knowledge/delete?knowledge_map_id=${knowledge_map_id}`, {
    method: "DELETE",
    headers: {
      "Content-Type": "application/json",
    },
  });
};

export const generateAnswers = async (knowledge_map_id: number) => {
  return fetch(`/api/knowledge/answers`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      knowledge_map_id,
    }),
  });
};
