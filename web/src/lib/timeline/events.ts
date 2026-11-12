import type { RateLimitDetails } from "@/app/app/types";
import type { AcpSessionUpdate, AcpStopReason } from "@/lib/timeline/acp";

/**
 * Onyx-only events, sent as ACP extension notifications. ACP reserves method
 * names that start with `_` for extensions.
 */
export type OnyxNotification =
  /** The agent compacted its context to continue. */
  | { method: "_onyx/compaction"; params: { summary: string | null } }
  /** A tool waits until the user connects an external app. */
  | {
      method: "_onyx/connect_app_request";
      params: {
        requestId: string;
        externalAppId: number;
        reason: string | null;
      };
    };

/**
 * One event of an agent turn, in arrival order. Each product's adapter turns
 * its own stream into these events; the reducer turns them into a timeline.
 */
export type TimelineEvent =
  /** An ACP `session/update` notification. */
  | { type: "update"; update: AcpSessionUpdate }
  /** An Onyx extension notification. */
  | { type: "ext"; notification: OnyxNotification }
  /** The turn ended, with the reason from ACP's prompt response. */
  | { type: "stop"; stopReason: AcpStopReason }
  /** The turn failed. A usage-limit failure carries its limit details. */
  | { type: "error"; message: string; rateLimit?: RateLimitDetails };
