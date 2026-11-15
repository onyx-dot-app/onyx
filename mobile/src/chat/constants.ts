// Batched-flush window shared by the send + resume streams so both render at the same cadence.
export const FLUSH_INTERVAL_MS = 50;

// Pause between server status reads while a client waits on the session.
export const SESSION_POLL_INTERVAL_MS = 1000;
