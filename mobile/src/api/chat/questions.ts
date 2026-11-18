import { apiFetch } from "@/api/client";
import type { ChatStream } from "@/chat/interfaces";
import type { ToolQuestionAnswer } from "@/chat/streamingModels";

// The card's answers to each question of the request, or a message that the user typed in the chat,
// which answers every question of the response that waits.
export type QuestionAnswersBody =
  { answers: ToolQuestionAnswer[] } | { message: string };

export interface QuestionAnswersResponse {
  question_request_id: string;
  // The stream that continues the suspended response, when this answer started or found it.
  continuation: ChatStream | null;
}

// 404 or 409: the question no longer waits. 409 APPROVAL_PENDING: a message while an approval
// request of the response waits.
export function postQuestionAnswers(
  questionRequestId: string,
  body: QuestionAnswersBody,
): Promise<QuestionAnswersResponse> {
  return apiFetch<QuestionAnswersResponse>(
    `/chat/question-requests/${encodeURIComponent(questionRequestId)}/answers`,
    { method: "POST", body },
  );
}
