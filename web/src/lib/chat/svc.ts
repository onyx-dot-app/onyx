import { fetchErrorFrom } from "@/lib/fetcher";
import type {
  ApprovalDecisionResponse,
  QuestionAnswersBody,
  QuestionAnswersResponse,
} from "@/lib/chat/types";
import type { ApprovalSubmitDecision } from "@/lib/approvals/types";

const CHAT_FILE_PREFIX = "/api/chat/file";

/**
 * The form of a chat file to fetch: the stored bytes; a spreadsheet's sheets
 * as a JSON payload of per-sheet CSV text; the stored PDF of a Word or
 * PowerPoint file (`pdf`); or that PDF made now in the owner's sandbox
 * (`convertPdf`), which returns the stored PDF when one exists. The server
 * ignores `parsed` for a file that is not a spreadsheet.
 */
export type ChatFileVariant = "original" | "parsed" | "pdf" | "convertPdf";

const CHAT_FILE_VARIANT_REQUEST: Record<
  ChatFileVariant,
  { method: "GET" | "POST"; suffix: string }
> = {
  original: { method: "GET", suffix: "" },
  parsed: { method: "GET", suffix: "?parsed=true" },
  pdf: { method: "GET", suffix: "?preview=pdf" },
  convertPdf: { method: "POST", suffix: "/preview" },
};

/**
 * Fetch a chat file by its ID, returning the raw Response.
 *
 * The caller is responsible for consuming the body (e.g. `.blob()`,
 * `.text()`) since different consumers need different formats.
 *
 * Throws a `FetchError`. With `pdf` or `convertPdf`, status 422 and error
 * code `PREVIEW_UNAVAILABLE` mean that the server cannot make a PDF of the
 * file. With `pdf`, status 409 and error code `PREVIEW_NOT_READY` mean that
 * the file has no stored PDF yet; `convertPdf` makes it.
 */
export async function fetchChatFile(
  fileId: string,
  variant: ChatFileVariant = "original",
  signal?: AbortSignal
): Promise<Response> {
  const { method, suffix } = CHAT_FILE_VARIANT_REQUEST[variant];
  const response = await fetch(
    `${CHAT_FILE_PREFIX}/${encodeURIComponent(fileId)}${suffix}`,
    // The server marks a GET file immutable; the default cache mode reuses
    // it and fetches a failed load again.
    { method, signal }
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
