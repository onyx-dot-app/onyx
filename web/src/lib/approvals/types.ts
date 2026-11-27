/**
 * A user's decision on an approval request, in Craft and in chat.
 * "approve_command": only for an app request of a chat's VM command.
 */
export type ApprovalSubmitDecision =
  | "approve_once"
  | "approve_session"
  | "approve_command"
  | "reject";

/**
 * "approvedForSession": approved, along with later requests of the same action
 * in this Craft session, chat, or VM command. "disabled": an approval found the action
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
