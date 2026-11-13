/** A user's decision on an approval request, in Craft and in chat. */
export type ApprovalSubmitDecision =
  | "approve_once"
  | "approve_session"
  | "reject";

/**
 * "approvedForSession": approved, along with later requests of the same action
 * in this Craft session or chat. "disabled": an approval found the action
 * disabled by a policy, so it did not run. "closed": nothing waits for
 * a decision any more, and the outcome is unknown.
 */
export type ApprovalStatus =
  | "pending"
  | "approved"
  | "approvedForSession"
  | "rejected"
  | "expired"
  | "disabled"
  | "closed";
