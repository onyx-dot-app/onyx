import { fetchErrorFrom } from "@/lib/fetcher";
import type {
  ApprovalDecisionResponse,
  QuestionAnswersBody,
  QuestionAnswersResponse,
} from "@/lib/chat/types";
import type { ApprovalSubmitDecision } from "@/lib/approvals/types";

const CHAT_FILE_PREFIX = "/api/chat/file";

/**
 * The form of a chat file to fetch: the stored bytes, a spreadsheet's sheets
 * as a JSON payload of per-sheet CSV text, or a Word or PowerPoint file as a
 * PDF that the server converts. The server ignores `parsed` for a file that is
 * not a spreadsheet.
 */
export type ChatFileVariant = "original" | "parsed" | "pdf";

const CHAT_FILE_VARIANT_QUERY: Record<ChatFileVariant, string> = {
  original: "",
  parsed: "?parsed=true",
  pdf: "?preview=pdf",
};

/**
 * Fetch a chat file by its ID, returning the raw Response.
 *
 * The caller is responsible for consuming the body (e.g. `.blob()`,
 * `.text()`) since different consumers need different formats.
 *
 * Throws a `FetchError`. With `pdf`, status 422 and error code
 * `PREVIEW_UNAVAILABLE` mean that the server cannot make a PDF of the file.
 */
export async function fetchChatFile(
  fileId: string,
  variant: ChatFileVariant = "original",
  signal?: AbortSignal
): Promise<Response> {
  const response = await fetch(
    `${CHAT_FILE_PREFIX}/${encodeURIComponent(fileId)}${CHAT_FILE_VARIANT_QUERY[variant]}`,
    // The server marks a file immutable; the default cache mode reuses it
    // and fetches a failed load again.
    { method: "GET", signal }
  );

  if (!response.ok) {
    throw await fetchErrorFrom(response, "Failed to load document.");
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
