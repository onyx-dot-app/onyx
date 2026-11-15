/** A user's decision on an approval request. */
export type ApprovalSubmitDecision =
  | "approve_once"
  | "approve_session"
  | "reject";

/**
 * "approvedForSession": approved, along with later requests of the same action
 * in this session. "closed": nothing waits for a decision any more, and the
 * outcome is unknown.
 */
export type ApprovalStatus =
  | "pending"
  | "approved"
  | "approvedForSession"
  | "rejected"
  | "expired"
  | "closed";
