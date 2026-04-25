export interface Topic {
  id: number;
  name: string;
  description: string;
  watch_path: string;
}

export interface TopicCreate {
  name: string;
  description: string;
  watch_path: string;
}

export const createTopic = async (body: TopicCreate): Promise<Response> =>
  fetch("/api/knowledge/topics", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const deleteTopic = async (id: number): Promise<Response> =>
  fetch(`/api/knowledge/topics/${id}`, { method: "DELETE" });
