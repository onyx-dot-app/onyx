// Context-window gauge data, derived from the backend's context_usage stream
// packet or the session-detail API's session-level context_usage object.
export interface ContextUsage {
  used_tokens: number;
  max_input_tokens: number;
  // True when sourced from a session-level baseline rather than a live turn packet.
  is_baseline: boolean;
}
