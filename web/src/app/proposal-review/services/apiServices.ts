// ---------------------------------------------------------------------------
// Proposal Review API Services
//
// All mutation (POST) calls for the proposal-review feature.
// GET requests are handled by SWR hooks — see hooks/.
// ---------------------------------------------------------------------------

const BASE = "/api/proposal-review";

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? body.message ?? "Request failed");
  }
  return res.json();
}

/** Trigger an AI review for a proposal with a given ruleset. */
export async function triggerReview(
  proposalId: string,
  rulesetId: string
): Promise<{ id: string }> {
  const res = await fetch(`${BASE}/proposals/${proposalId}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ruleset_id: rulesetId }),
  });
  return handleResponse(res);
}

/** Record an officer decision on an individual finding. */
export async function submitFindingDecision(
  findingId: string,
  action: string,
  notes?: string
): Promise<void> {
  const res = await fetch(`${BASE}/findings/${findingId}/decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, notes: notes ?? null }),
  });
  return handleResponse(res);
}

/** Record the final proposal-level decision. */
export async function submitProposalDecision(
  proposalId: string,
  decision: string,
  notes?: string
): Promise<void> {
  const res = await fetch(`${BASE}/proposals/${proposalId}/decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision, notes: notes ?? null }),
  });
  return handleResponse(res);
}

/** Sync the proposal decision to Jira. */
export async function syncToJira(proposalId: string): Promise<void> {
  const res = await fetch(`${BASE}/proposals/${proposalId}/sync-jira`, {
    method: "POST",
  });
  return handleResponse(res);
}

/** Upload a document for a proposal. */
export async function uploadDocument(
  proposalId: string,
  file: File,
  documentRole: string
): Promise<void> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("document_role", documentRole);

  const res = await fetch(`${BASE}/proposals/${proposalId}/documents`, {
    method: "POST",
    body: formData,
  });
  return handleResponse(res);
}
