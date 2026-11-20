import { fetchErrorFrom } from "@/lib/fetcher";
import type {
  ApprovalDecisionResponse,
  QuestionAnswersBody,
  QuestionAnswersResponse,
} from "@/lib/chat/types";
import type { ApprovalSubmitDecision } from "@/lib/approvals/types";

const CHAT_FILE_PREFIX = "/api/chat/file";

/**
 * Fetch a chat file by its ID, returning the raw Response.
 *
 * The caller is responsible for consuming the body (e.g. `.blob()`,
 * `.text()`) since different consumers need different formats.
 *
 * When `parsed` is true, spreadsheet files (xlsx) are returned as a JSON
 * payload of per-sheet CSV text instead of raw binary bytes; the param is a
 * no-op for all other file types.
 */
export async function fetchChatFile(
  fileId: string,
  parsed: boolean = false,
  signal?: AbortSignal
): Promise<Response> {
  const response = await fetch(
    `${CHAT_FILE_PREFIX}/${encodeURIComponent(fileId)}${
      parsed ? "?parsed=true" : ""
    }`,
    // The server marks a file immutable; the default cache mode reuses it
    // and fetches a failed load again.
    { method: "GET", signal }
  );

  if (!response.ok) {
    throw new Error("Failed to load document.");
  }

  return response;
}

/** Throws a `FetchError`; status 409 means the request was already resolved.
 * "approve_session" also approves later calls of the same tool in this chat. */
export async function postChatApprovalDecision(
  approvalId: string,
  decision: ApprovalSubmitDecision
): Promise<ApprovalDecisionResponse> {
  const response = await fetch(
    `/api/chat/approvals/${encodeURIComponent(approvalId)}/decision`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision }),
    }
  );
  if (!response.ok) {
    throw await fetchErrorFrom(
      response,
      `Failed to submit the approval decision: ${response.status}`
    );
  }
  return response.json();
}

/** Throws a `FetchError`; status 409 means the question no longer waits or
 * has a different answer, or, with error code APPROVAL_PENDING, that an
 * approval of the response still waits. */
export async function postQuestionAnswers(
  questionRequestId: string,
  body: QuestionAnswersBody
): Promise<QuestionAnswersResponse> {
  const response = await fetch(
    `/api/chat/question-requests/${encodeURIComponent(questionRequestId)}/answers`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }
  );
  if (!response.ok) {
    throw await fetchErrorFrom(
      response,
      `Failed to submit the answers: ${response.status}`
    );
  }
  return response.json();
}
