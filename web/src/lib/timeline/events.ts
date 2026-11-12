import type { AcpSessionUpdate, AcpStopReason } from "@/lib/timeline/acp";

/**
 * One event of an agent turn, in arrival order. Each product's adapter turns
 * its own stream into these events; the reducer turns them into a timeline.
 */
export type TimelineEvent =
  /** An ACP `session/update` notification. */
  | { type: "update"; update: AcpSessionUpdate }
  /** The turn ended, with the reason from ACP's prompt response. */
  | { type: "stop"; stopReason: AcpStopReason }
  /** The turn failed. */
  | { type: "error"; message: string };
